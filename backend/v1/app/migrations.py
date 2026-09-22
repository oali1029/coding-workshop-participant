"""Creating and updating the database tables automatically.

=============================================================================
WHAT THIS FILE IS RESPONSIBLE FOR
=============================================================================
A brand-new database is empty — no tables, no columns. Something has to create
them. That job is called a "migration", and this file performs migrations
automatically the first time the application runs.

Why automatically? Because this application is deployed by a shell script to a
database that may have just been created moments earlier by Terraform. There
is no human to log in and run SQL by hand, and no separate deployment step
where we could. Doing it here means "deploy the code" and "prepare the
database" are one action that cannot get out of step.

=============================================================================
HOW VERSIONING WORKS
=============================================================================
We keep a list of numbered changes in `_MIGRATIONS` below, and a table in the
database called `schema_migrations` recording which numbers have already run.

On startup we compare the two and run only what is missing. So:

  * A fresh database runs every migration, in order.
  * An up-to-date database runs nothing and costs almost no time.
  * Adding a feature later means APPENDING a new numbered entry. We never edit
    an existing one, because it has already run on deployed databases and
    would never run again.

This is why the code below never uses `DROP TABLE` or destructive statements.
Migrations must be safe to apply to a database that already holds real data.

=============================================================================
THE CONCURRENCY PROBLEM, AND THE ADVISORY LOCK
=============================================================================
Lambda can start many copies of our program at the same moment. If ten
requests arrive at once on a cold system, ten copies may all decide the
database needs migrating and all start creating the same table simultaneously.

`CREATE TABLE IF NOT EXISTS` protects us from crashing, but the bookkeeping
inserts could still duplicate or interleave badly.

The fix is a PostgreSQL "advisory lock". It is a lock the database maintains
on behalf of the application, attached to a number we invent. The rule is
simple: whoever asks for it first gets it, and everyone else waits at that
line until it is released. So the first copy migrates while the others queue;
by the time they proceed, the work is recorded as done and they skip it.

IMPORTANT SUBTLETY: we use `pg_advisory_xact_lock`, the transaction-scoped
variant, which is released automatically when the transaction ends — including
if the Lambda crashes mid-way. That is exactly what we want, since a Lambda can
be killed at any time and a lock that outlived it would freeze every future
request. But it only works INSIDE a transaction, and db.py deliberately opens
connections in autocommit mode where each statement is its own transaction.
That is why `run_migrations` opens an explicit `with conn.transaction():`
block below — without it, the lock would be released instantly and provide no
protection at all.

=============================================================================
WHY A MIGRATION CAN RUN PYTHON AS WELL AS SQL
=============================================================================
Most migrations are pure SQL. Migration 2 is not: it has to create the very
first administrator account, and that requires a hashed password. Hashing is a
deliberately slow, salted computation that SQL cannot perform.

So a migration may carry an optional `after` function, which runs with the same
cursor inside the same transaction as its SQL. If the Python step fails, the
table creation rolls back with it, and we never end up with a users table that
has no way to administer it.
"""

import logging
from dataclasses import dataclass
from typing import Any, Callable

from . import db, security

logger = logging.getLogger(__name__)

# An arbitrary but FIXED number identifying our migration lock. The exact value
# is meaningless; what matters is that every copy of the program uses the same
# one, because PostgreSQL matches locks by number. Changing it later would
# allow two copies to migrate simultaneously, so it must stay put.
_ADVISORY_LOCK_KEY = 8_531_204_771


@dataclass(frozen=True)
class Migration:
    """One numbered change to the database schema.

    Attributes:
        version: Order of application. Must be unique and never reused.
        name: Short human label, recorded alongside the version.
        sql: Statements to run. Must be safe to re-run, so always
            `CREATE TABLE IF NOT EXISTS` and similar.
        after: Optional Python step run with the same cursor, in the same
            transaction, immediately after the SQL. Used when a migration needs
            to compute something SQL cannot.
    """

    version: int
    name: str
    sql: str
    after: Callable[[Any], None] | None = None


def ensure_bootstrap_admin() -> bool:
    """Create the bootstrap Facility Admin account if it does not exist yet.

    WHY THIS IS NECESSARY
    Self-registration deliberately only ever produces EMPLOYEE accounts, so that
    nobody can grant themselves elevated access simply by signing up. That rule
    creates a chicken-and-egg problem: without a seeded administrator, no
    FACILITY_ADMIN could ever come into existence.

    WHY THIS IS NOT PART OF A NUMBERED MIGRATION
    The password comes from an environment variable that may not have been
    supplied yet. If this ran inside migration 2 and the variable were missing,
    the migration would still be recorded as applied, and the administrator
    would never be created — not even after the variable was later provided,
    because a migration never runs twice.

    Running it separately on every startup makes it self-healing instead: supply
    the variable and redeploy, and the account appears on the next request.

    IT CREATES, IT DOES NOT RESET
    `ON CONFLICT DO NOTHING` means an existing administrator is left completely
    alone. If the password has since been changed, a later deployment cannot
    silently revert it to whatever the deployer's environment happens to hold.

    Returns:
        True if an account was created by this call, False if one already
        existed or no password was available.
    """
    password = security.get_bootstrap_admin_password()

    if password is None:
        # Not fatal. The application runs perfectly well without an
        # administrator; only administrative features are unavailable.
        logger.warning(
            "%s is not set — skipping bootstrap administrator creation. "
            "Set it and redeploy to create the %s account.",
            security.BOOTSTRAP_ADMIN_PASSWORD_VAR,
            security.SEED_ADMIN_EMAIL,
        )
        return False

    # RETURNING produces a row only when the insert actually happened, which is
    # how we distinguish "created it" from "it was already there" without a
    # separate query and the race that would come with one.
    #
    # Note what is NOT logged anywhere in this function: the password itself.
    # Only the hash reaches the database, and only the email reaches the logs.
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


# The ordered list of database changes.
#
# APPEND ONLY. Never renumber or edit an entry that has already been deployed.
_MIGRATIONS: list[Migration] = [
    Migration(
        version=1,
        name="bootstrap",
        # `app_config` is a general-purpose key/value table for settings that
        # must be generated once and then shared by every copy of the running
        # application. Its first real use is the secret key used to sign login
        # tokens (see security.get_signing_key).
        #
        # Why the database rather than an environment variable? Because every
        # Lambda copy must use the SAME key — a token signed by one copy has to
        # be accepted by all the others. Generating it per copy would log users
        # out at random. Storing it here means it is created once and read by
        # everyone.
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
        # The people who use the system. Every later feature — who reported an
        # incident, who it is assigned to, who wrote a note — points back here.
        #
        # Notes on specific choices:
        #
        # email ... UNIQUE
        #   Addresses are lower-cased and trimmed in Python before they are
        #   written (security.normalize_email), so a plain UNIQUE constraint is
        #   enough to guarantee one account per person. Doing it this way avoids
        #   depending on the `citext` extension being installed on Aurora.
        #
        # password_hash
        #   Never the password itself. See the long explanation at the top of
        #   security.py.
        #
        # is_active
        #   Lets an account be switched off without deleting it, which would
        #   otherwise orphan every incident that person ever reported.
        #
        # users_role_valid / users_email_domain
        #   Defence in depth. The React form checks the email domain for the
        #   user's convenience and the backend checks it for real, but these
        #   constraints mean that even a bug in our Python — or someone with
        #   direct database access — cannot insert an invalid role or an
        #   outsider's address.
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

        -- Login looks users up by email on every attempt. The UNIQUE constraint
        -- above already creates an index, so no extra index is needed here.
        CREATE INDEX IF NOT EXISTS users_role_idx ON users (role);
        """,
        # No `after` step. The bootstrap administrator is created by
        # ensure_bootstrap_admin() on every startup instead of here — see that
        # function for why a one-time migration is the wrong place for it.
    ),
]


def _ensure_version_table() -> None:
    """Create the table that records which migrations have run.

    A chicken-and-egg problem: we cannot look up which migrations have been
    applied until the table holding that information exists. So this one table
    is created separately, before and outside the numbered list.

    `IF NOT EXISTS` makes it harmless to call on every single startup.
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
    """Report which migration version the database is currently at.

    In plain English the SQL asks: "what is the largest version number in the
    migrations table, and if the table is empty, say 0 instead of nothing."
    `COALESCE` is the part that substitutes 0 for an empty result, so callers
    always get a number back.

    Returns:
        The highest applied version, or 0 on a database that has never been
        migrated.
    """
    row = db.query_one("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations")
    return int(row["version"]) if row else 0


def run_migrations() -> int:
    """Apply any migrations the database has not yet seen.

    Called once per Lambda startup from ../function.py. Safe to call
    concurrently from many copies at once — see the module docstring for how
    the advisory lock makes that true.

    Returns:
        The version number the database is at once this finishes.
    """
    # Step 1: make sure we can record our work, before doing any of it.
    _ensure_version_table()

    conn = db.get_connection()

    # Step 2: everything below happens inside ONE transaction. Two reasons:
    #   (a) `pg_advisory_xact_lock` is tied to a transaction and would be
    #       released immediately without it (see module docstring);
    #   (b) if a migration fails halfway, the whole batch rolls back, so we
    #       never record a version whose SQL did not actually complete.
    with conn.transaction():
        with conn.cursor() as cur:
            # Step 3: queue up. This call BLOCKS — it does not return until
            # this copy of the program holds the lock. Any other copy doing the
            # same thing waits here.
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_ADVISORY_LOCK_KEY,))

            # Step 4: re-read the version now that we hold the lock. Reading it
            # earlier would be unsafe: another copy may have migrated while we
            # were queueing, and acting on that stale number is exactly the
            # race the lock exists to prevent.
            cur.execute("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations")
            row = cur.fetchone()
            applied = int(row["version"]) if row else 0

            # Step 5: run everything newer than what is recorded, in order.
            for migration in _MIGRATIONS:
                if migration.version <= applied:
                    continue

                logger.info("Applying migration %s_%s", migration.version, migration.name)
                cur.execute(migration.sql)

                # The optional Python step, inside the same transaction so it
                # rolls back with the SQL if it fails.
                if migration.after is not None:
                    migration.after(cur)

                # Record it in the same transaction as the change itself, so
                # the schema and its version can never disagree.
                cur.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
                    (migration.version, migration.name),
                )
                applied = migration.version

    # Step 6: the transaction has committed and the lock is released, so any
    # waiting copies can now proceed — and will find nothing left to do.
    return applied
