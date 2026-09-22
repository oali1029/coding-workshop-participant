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
SCOPE RIGHT NOW
=============================================================================
This is Slice 0, the "walking skeleton": the smallest version of the system
that can be deployed end to end. It creates only the bookkeeping tables, which
is enough to prove that migrations work against the real cloud database.
Tables for users, incidents, and facilities arrive in later slices as new
numbered entries.
"""

import logging

from . import db

logger = logging.getLogger(__name__)

# An arbitrary but FIXED number identifying our migration lock. The exact value
# is meaningless; what matters is that every copy of the program uses the same
# one, because PostgreSQL matches locks by number. Changing it later would
# allow two copies to migrate simultaneously, so it must stay put.
_ADVISORY_LOCK_KEY = 8_531_204_771

# The ordered list of database changes: (version, name, SQL).
#
# APPEND ONLY. Never renumber or edit an entry that has already been deployed.
_MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "bootstrap",
        # `app_config` is a general-purpose key/value table for settings that
        # must be generated once and then shared by every copy of the running
        # application. Its first real use arrives in the next slice: the secret
        # key used to sign login tokens.
        #
        # Why the database rather than an environment variable? Because every
        # Lambda copy must use the SAME key — a token signed by one copy has to
        # be accepted by all the others. Generating it per copy would log users
        # out at random. Storing it here means it is created once and read by
        # everyone.
        """
        CREATE TABLE IF NOT EXISTS app_config (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """,
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
            for version, name, statements in _MIGRATIONS:
                if version <= applied:
                    continue

                logger.info("Applying migration %s_%s", version, name)
                cur.execute(statements)

                # Record it in the same transaction as the change itself, so
                # the schema and its version can never disagree.
                cur.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
                    (version, name),
                )
                applied = version

    # Step 6: the transaction has committed and the lock is released, so any
    # waiting copies can now proceed — and will find nothing left to do.
    return applied
