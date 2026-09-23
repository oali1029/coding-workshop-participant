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
