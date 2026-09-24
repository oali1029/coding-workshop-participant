"""Schema creation and versioning, applied automatically at startup.

There is no separate deployment step where a human could run SQL: a shell
script deploys the code to a database Terraform may have created minutes
earlier. Running migrations on startup keeps "deploy the code" and "prepare the
database" as one action that cannot get out of step.

``_MIGRATIONS`` is append-only. Entries already applied to a deployed database
will never run again, so editing one silently produces divergent schemas.
Statements must be idempotent, and never destructive.

Concurrency: Lambda can start many copies at once, all deciding the database
needs migrating. A PostgreSQL advisory lock serialises them, so the first
migrates and the rest wait and then find nothing to do. It has to be taken
inside an explicit transaction — ``pg_advisory_xact_lock`` is released when the
transaction ends, and db.py connects in autocommit mode where each statement
would be its own transaction, releasing the lock immediately.
"""

import logging
from dataclasses import dataclass

from . import db, security

logger = logging.getLogger(__name__)

# Arbitrary but fixed: PostgreSQL matches advisory locks by number, so every
# copy must use the same one.
_ADVISORY_LOCK_KEY = 8_531_204_771


@dataclass(frozen=True)
class Migration:
    """One numbered schema change."""

    version: int
    name: str
    sql: str


def ensure_bootstrap_admin() -> bool:
    """Create the bootstrap Facility Admin if it does not already exist.

    Deliberately not part of a numbered migration. Its password comes from an
    environment variable that may not be set yet, and a migration runs only
    once — so a skipped seed would never get another chance, even after the
    variable was supplied. Running it every startup makes it self-healing.

    It creates but never resets: an existing administrator is left alone, so a
    later deployment cannot silently revert a password that has been changed.

    Returns:
        True if an account was created by this call.
    """
    password = security.get_bootstrap_admin_password()

    if password is None:
        logger.warning(
            "%s is not set — skipping bootstrap administrator creation. "
            "Set it and redeploy to create the %s account.",
            security.BOOTSTRAP_ADMIN_PASSWORD_VAR,
            security.SEED_ADMIN_EMAIL,
        )
        return False

    # RETURNING yields a row only when the insert actually happened, which
    # distinguishes "created" from "already existed" without a second query and
    # the race that would come with it. Note that the password is never logged;
    # only its hash leaves this function.
    created = db.query_one(
        """
        INSERT INTO users (email, password_hash, full_name, role)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (email) DO NOTHING
        RETURNING id
        """,
        (
            security.SEED_ADMIN_EMAIL,
            security.hash_password(password),
            security.SEED_ADMIN_NAME,
            security.ROLE_FACILITY_ADMIN,
        ),
    )

    if created is not None:
        logger.info("Created the bootstrap administrator account %s", security.SEED_ADMIN_EMAIL)
        return True

    logger.info("Bootstrap administrator account already exists; left unchanged")
    return False


_MIGRATIONS: list[Migration] = [
    Migration(
        version=1,
        name="bootstrap",
        # Key/value store for settings generated once and shared by every
        # running copy — currently the JWT signing key, which must be identical
        # across copies or tokens would be rejected at random.
        sql="""
        CREATE TABLE IF NOT EXISTS app_config (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """,
    ),
    Migration(
        version=2,
        name="users",
        # Emails are lower-cased in Python before insert, so plain UNIQUE is
        # enough and no citext extension is needed on Aurora.
        #
        # is_active allows disabling an account without deleting it, which
        # would orphan every incident that person reported.
        #
        # The two CHECK constraints are defence in depth: the email domain rule
        # is also enforced in the React form and in the backend, but these hold
        # even against a bug in our code or direct database access.
        sql="""
        CREATE TABLE IF NOT EXISTS users (
            id            BIGSERIAL PRIMARY KEY,
            email         TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name     TEXT NOT NULL,
            role          TEXT NOT NULL DEFAULT 'EMPLOYEE',
            is_active     BOOLEAN NOT NULL DEFAULT TRUE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT users_role_valid
                CHECK (role IN ('EMPLOYEE', 'ENGINEER', 'FACILITY_ADMIN')),
            CONSTRAINT users_email_domain
                CHECK (email LIKE '%@acme.inc')
        );

        CREATE INDEX IF NOT EXISTS users_role_idx ON users (role);
        """,
        # The administrator is seeded by ensure_bootstrap_admin() on every
        # startup instead of here — see that function.
    ),
    Migration(
        version=3,
        name="incidents",
        # Facility and workplace-technology issues reported by staff.
        #
        # location is deliberately free text for now. The real building / floor
        # / seat model arrives in a later slice; modelling it early would mean
        # guessing at a schema before the requirements for it are built.
        #
        # created_by is a foreign key with no ON DELETE clause, so PostgreSQL
        # refuses to delete a user who still has incidents. That is the
        # behaviour we want: incident history should outlive an account, and
        # accounts are disabled via users.is_active rather than deleted.
        #
        # The CHECK constraints list every status the product will eventually
        # use, not just the one reachable today, so later slices can move
        # incidents through the workflow without another migration.
        sql="""
        CREATE TABLE IF NOT EXISTS incidents (
            id          BIGSERIAL PRIMARY KEY,
            title       TEXT NOT NULL,
            description TEXT NOT NULL,
            category    TEXT NOT NULL,
            priority    TEXT NOT NULL DEFAULT 'MEDIUM',
            status      TEXT NOT NULL DEFAULT 'OPEN',
            location    TEXT,
            created_by  BIGINT NOT NULL REFERENCES users (id),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT incidents_category_valid CHECK (category IN
                ('TECHNOLOGY', 'ELECTRICAL', 'PLUMBING', 'HVAC', 'FURNITURE', 'OTHER')),
            CONSTRAINT incidents_priority_valid CHECK (priority IN
                ('LOW', 'MEDIUM', 'HIGH')),
            CONSTRAINT incidents_status_valid CHECK (status IN
                ('OPEN', 'IN_PROGRESS', 'BLOCKED', 'RESOLVED', 'CLOSED'))
        );

        -- Serves the only list query this slice has: one user's incidents,
        -- newest first. A composite index covers both the filter and the sort.
        CREATE INDEX IF NOT EXISTS incidents_created_by_idx
            ON incidents (created_by, created_at DESC);
        """,
    ),
    Migration(
        version=4,
        name="incident_assignment",
        # Who is working the incident, as opposed to who reported it.
        #
        # Nullable because incidents arrive unassigned — reporting and triage are
        # separate acts. No ON DELETE clause, matching created_by: PostgreSQL then
        # refuses to delete a user still holding work, and accounts are disabled
        # via is_active rather than deleted.
        #
        # Only users whose role is ENGINEER may be assigned. That is enforced in
        # the handler rather than by a constraint, because a CHECK cannot read
        # another table and a trigger would hide the rule from the code.
        sql="""
        ALTER TABLE incidents
            ADD COLUMN IF NOT EXISTS assignee_id BIGINT REFERENCES users (id);

        -- Serves the engineer work queue: one assignee's incidents, newest first.
        CREATE INDEX IF NOT EXISTS incidents_assignee_idx
            ON incidents (assignee_id, created_at DESC);
        """,
    ),
    Migration(
        version=5,
        name="facilities",
        # The estate — Building > Floor > Seat — and where each incident happened.
        #
        # Deleting a building CASCADEs to its floors and seats, but only SETs NULL
        # on incidents: CASCADE there would delete history, RESTRICT would make
        # buildings undeletable. location_snapshot keeps the incident readable
        # after the references are gone.
        #
        # The incident columns are nullable even though building and floor are
        # required when reporting — older incidents predate them, and SET NULL
        # needs nullability. The create handler enforces the requirement.
        #
        # building_id sits on the incident directly, not only via floor_id, so
        # grouping incidents by building needs no joins.
        sql="""
        CREATE TABLE IF NOT EXISTS buildings (
            id         BIGSERIAL PRIMARY KEY,
            name       TEXT NOT NULL UNIQUE,
            address    TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        -- Names are unique per parent, not globally: every building has a "Floor 3".
        CREATE TABLE IF NOT EXISTS floors (
            id          BIGSERIAL PRIMARY KEY,
            building_id BIGINT NOT NULL REFERENCES buildings (id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT floors_unique_per_building UNIQUE (building_id, name)
        );

        CREATE TABLE IF NOT EXISTS seats (
            id         BIGSERIAL PRIMARY KEY,
            floor_id   BIGINT NOT NULL REFERENCES floors (id) ON DELETE CASCADE,
            code       TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT seats_unique_per_floor UNIQUE (floor_id, code)
        );

        CREATE INDEX IF NOT EXISTS floors_building_idx ON floors (building_id, name);
        CREATE INDEX IF NOT EXISTS seats_floor_idx ON seats (floor_id, code);

        ALTER TABLE incidents
            ADD COLUMN IF NOT EXISTS building_id BIGINT
                REFERENCES buildings (id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS floor_id BIGINT
                REFERENCES floors (id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS seat_id BIGINT
                REFERENCES seats (id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS location_snapshot TEXT;

        CREATE INDEX IF NOT EXISTS incidents_building_idx ON incidents (building_id);
        """,
    ),
    Migration(
        version=6,
        name="incident_comments",
        # Conversation on a ticket between the reporter, the assigned engineer
        # and the admin.
        #
        # Comments belong to their incident, so deleting one takes its comments
        # with it (CASCADE). author_id has no ON DELETE clause, matching
        # created_by on incidents: a comment must always say who wrote it, and
        # accounts are disabled rather than deleted.
        #
        # There is no updated_at, and no update or delete endpoint. Comments are
        # a permanent record of what was said and when.
        sql="""
        CREATE TABLE IF NOT EXISTS incident_comments (
            id          BIGSERIAL PRIMARY KEY,
            incident_id BIGINT NOT NULL REFERENCES incidents (id) ON DELETE CASCADE,
            author_id   BIGINT NOT NULL REFERENCES users (id),
            body        TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        -- The only query this table has: one incident's comments, oldest first.
        CREATE INDEX IF NOT EXISTS incident_comments_incident_idx
            ON incident_comments (incident_id, created_at);
        """,
    ),
    Migration(
        version=7,
        name="lifecycle_escalation_availability",
        # Four requirements at once, because they are all small columns on
        # existing tables and one migration is cheaper than four.
        #
        # LIFECYCLE TIMESTAMPS answer "how quickly are incidents acknowledged,
        # assigned and resolved?". updated_at cannot: it only remembers the most
        # recent change, so a ticket resolved on Tuesday and commented on Friday
        # would report the wrong duration. Each column records the FIRST time its
        # event happened and is never overwritten, so reopening a ticket does not
        # erase how long the original fix took.
        #
        # ESCALATION is a flag plus the reason, not a workflow. The reason
        # survives acknowledgement so the history still reads.
        #
        # blocked_reason answers the other half of "which incidents are escalated
        # or blocked, and why?".
        #
        # is_available sits on users rather than in an engineer_profiles table.
        # An engineer is a user with a role, so a separate table would mean a
        # join and a second row to keep in step for one boolean. It defaults TRUE
        # so existing engineers stay assignable.
        #
        # edited_at is NULL until a comment is edited, which makes it both the
        # timestamp and the "Edited" indicator without a second column.
        sql="""
        ALTER TABLE incidents
            ADD COLUMN IF NOT EXISTS acknowledged_at     TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS assigned_at         TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS resolved_at         TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS closed_at           TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS escalation_requested BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS escalation_reason   TEXT,
            ADD COLUMN IF NOT EXISTS escalated_at        TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS blocked_reason      TEXT;

        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS is_available BOOLEAN NOT NULL DEFAULT TRUE;

        ALTER TABLE incident_comments
            ADD COLUMN IF NOT EXISTS edited_at TIMESTAMPTZ;

        -- Partial index: the admin's "what needs my attention" query asks only
        -- for the escalated few, so indexing the FALSE majority would be wasted.
        CREATE INDEX IF NOT EXISTS incidents_escalated_idx
            ON incidents (escalation_requested)
            WHERE escalation_requested;
        """,
    ),
]


def _ensure_version_table() -> None:
    """Create the migration ledger.

    Kept outside the numbered list to break the chicken-and-egg problem: we
    cannot read which migrations have run until this table exists.
    """
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def current_version() -> int:
    """Highest applied migration version, or 0 on a fresh database."""
    row = db.query_one("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations")
    return int(row["version"]) if row else 0


def run_migrations() -> int:
    """Apply any outstanding migrations and return the resulting version.

    Safe to call concurrently from many Lambda copies; see the module docstring.
    """
    _ensure_version_table()

    conn = db.get_connection()

    # One transaction for the whole batch: it is what keeps the advisory lock
    # held, and it means a failure halfway cannot leave a version recorded for
    # SQL that did not complete.
    with conn.transaction():
        with conn.cursor() as cur:
            # Blocks until this copy holds the lock.
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_ADVISORY_LOCK_KEY,))

            # Read the version only after acquiring the lock — another copy may
            # have migrated while we queued, and acting on a stale number is
            # exactly the race the lock prevents.
            cur.execute("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations")
            row = cur.fetchone()
            applied = int(row["version"]) if row else 0

            for migration in _MIGRATIONS:
                if migration.version <= applied:
                    continue

                logger.info("Applying migration %s_%s", migration.version, migration.name)
                cur.execute(migration.sql)

                cur.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
                    (migration.version, migration.name),
                )
                applied = migration.version

    return applied
