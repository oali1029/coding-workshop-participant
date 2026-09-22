"""Connecting to PostgreSQL, and reusing that connection between requests.

=============================================================================
WHAT THIS FILE IS RESPONSIBLE FOR
=============================================================================
Every piece of information in this application — users, incidents, buildings,
notes — lives in a PostgreSQL database. This file is the only place that opens
a connection to it and sends SQL. Every other file asks this one.

=============================================================================
THE SAME CODE RUNS IN TWO VERY DIFFERENT PLACES
=============================================================================
This is one of the most important concepts in the project.

  ON A LAPTOP          PostgreSQL is installed directly on the machine. The
                       Lambda runs inside a Docker container, so from the
                       container's point of view the laptop is reachable at
                       the special address 172.17.0.1. No encryption is used,
                       because the traffic never leaves the machine.

  ON AWS               The database is Amazon Aurora, a managed PostgreSQL
                       service running on separate hardware. Traffic crosses a
                       network, so encryption (TLS) is REQUIRED — Aurora
                       refuses unencrypted connections outright.

We never hard-code either setup. The infrastructure code (infra/locals.tf)
detects which environment it is deploying to and injects the correct values as
environment variables: POSTGRES_HOST, POSTGRES_USER, and so on, plus a flag
called IS_LOCAL. This file reads those variables, so the identical Python runs
in both places. `build_conninfo()` below is where the one real difference —
encryption — is applied.

=============================================================================
WHY WE KEEP THE CONNECTION IN A GLOBAL VARIABLE
=============================================================================
Opening a database connection is slow: a network round trip, authentication,
and for Aurora a TLS handshake as well. That can take a noticeable fraction of
a second — far longer than the query itself.

AWS does not destroy a Lambda after each request. It keeps the loaded program
in memory for a while in case another request arrives soon; this is called a
"warm" invocation. Anything stored in a module-level variable survives between
those invocations.

So we open the connection once and store it in `_CONNECTION`. The first
request pays the setup cost; the next several hundred reuse it for free.

The catch is that a stored connection can go stale — the database may restart,
or a network device may silently drop an idle connection. Our defence is the
`cursor()` helper below: if anything at all goes wrong during a query, we throw
the connection away so the next request builds a fresh one. This
"reuse it, but discard it the moment it misbehaves" pattern is the standard
approach for databases in Lambda, and it is the pattern demonstrated in the
workshop's own example service.
"""

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

from psycopg import Connection, connect
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

# Holds the open connection between warm invocations. See the module docstring
# for why this is a global rather than being created per request.
_CONNECTION: Connection | None = None


def is_local() -> bool:
    """Report whether we are running on a laptop rather than on real AWS.

    The infrastructure sets the IS_LOCAL environment variable by inspecting
    which AWS account it is talking to; the local emulator always reports the
    fake account number 000000000000.

    Several behaviours branch on this, most importantly whether the database
    connection is encrypted.

    Returns:
        True when running against the local emulator.
    """
    return os.getenv("IS_LOCAL", "false").lower() == "true"


def build_conninfo() -> str:
    """Assemble the database connection string from environment variables.

    PostgreSQL accepts connection settings as a single string of
    "keyword=value" pairs. We build it from the variables the infrastructure
    injected, so that nothing about a specific environment is baked into the
    code or committed to version control.

    Returns:
        A connection string such as
        "host=... port=5432 user=... password=... dbname=... sslmode=require".

    Notes:
        The defaults in each `os.getenv` call match the local development
        setup. They exist so that a developer can run this file directly
        against a local database without any environment variables set.
        On AWS all five values are always supplied, so the defaults are never
        reached there.
    """
    parts = [
        f"host={os.getenv('POSTGRES_HOST', 'localhost')}",
        f"port={os.getenv('POSTGRES_PORT', '5432')}",
        f"user={os.getenv('POSTGRES_USER', 'postgres')}",
        f"password={os.getenv('POSTGRES_PASS', 'postgres123')}",
        f"dbname={os.getenv('POSTGRES_NAME', 'postgres')}",
        # Give up rather than hang forever if the database is unreachable.
        # Without this, a networking misconfiguration would make the Lambda sit
        # silently until its 300-second timeout, which is both slow to notice
        # and expensive.
        "connect_timeout=15",
    ]

    # THE key environment difference. Aurora rejects unencrypted connections;
    # the local PostgreSQL is not configured for TLS and would reject an
    # encrypted one. Asking for the wrong mode fails immediately, so this
    # single line is what allows one codebase to serve both environments.
    if not is_local():
        parts.append("sslmode=require")

    return " ".join(parts)


def get_connection() -> Connection:
    """Return the shared connection, opening one if we do not have a usable one.

    Called by every other function in this file. Most of the time it simply
    hands back the existing connection without doing any work.

    Returns:
        An open psycopg connection.

    Raises:
        psycopg.Error: If a new connection cannot be established — wrong
            password, database asleep, or no network route to it.
    """
    global _CONNECTION

    # `.closed` catches the case where the connection object still exists but
    # the underlying network socket has been shut down.
    if _CONNECTION is None or _CONNECTION.closed:
        logger.info("Opening a new PostgreSQL connection")
        _CONNECTION = connect(
            build_conninfo(),
            # Without this, psycopg returns each row as a plain tuple, so code
            # would read row[3] and have to remember what column 3 was. With
            # dict_row we get {"id": 1, "title": "Broken AC"} and can write
            # row["title"], which survives someone adding a column later.
            row_factory=dict_row,
            # Send each statement immediately instead of holding an open
            # transaction until something calls commit(). A Lambda handles one
            # request and may be frozen at any moment; an uncommitted
            # transaction left behind would hold database locks that block
            # other users. Code that genuinely needs several statements to
            # succeed or fail together opens an explicit transaction instead —
            # see migrations.py for an example.
            autocommit=True,
        )
    return _CONNECTION


def reset_connection() -> None:
    """Throw away the stored connection so the next call opens a fresh one.

    Called whenever a query fails. We cannot tell the difference between "that
    particular SQL was wrong" and "this connection is broken", so we assume the
    worse case. Reconnecting costs a few hundred milliseconds once; continuing
    to use a dead connection would fail every request until the Lambda is
    recycled, which could be hours.
    """
    global _CONNECTION

    if _CONNECTION is not None and not _CONNECTION.closed:
        try:
            _CONNECTION.close()
        except Exception:  # noqa: BLE001
            # Deliberately swallowed. We are already handling a failure, and a
            # secondary error while tidying up must not replace the original
            # error that the caller actually needs to see.
            logger.warning("Failed to close the PostgreSQL connection cleanly")

    _CONNECTION = None


@contextmanager
def cursor() -> Iterator[Any]:
    """Provide a cursor for running SQL, discarding the connection on failure.

    A "cursor" is the object you execute SQL through and read results from.
    The `@contextmanager` decorator lets this be used with `with`:

        with cursor() as cur:
            cur.execute("SELECT 1")

    and guarantees cleanup runs even if the body raises.

    Yields:
        A cursor that returns rows as dictionaries.

    Raises:
        Exception: Whatever the SQL raised, re-raised unchanged after the
            connection has been discarded. We deliberately do not convert it
            into a friendly error here — that decision belongs to the handler,
            which knows whether a failure means "not found" or "server error".
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            yield cur
    except Exception:
        # Any failure at all invalidates our assumption that the stored
        # connection is healthy. See reset_connection() for the reasoning.
        reset_connection()
        raise


def query_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Run a query and return every matching row.

    Args:
        sql: SQL text with %s placeholders for any values.
        params: The values to substitute into those placeholders.

    Returns:
        A list of rows, each a dictionary of column name to value. An empty
        list when nothing matched — not None, so callers can always loop.

    Security:
        Values must ALWAYS be passed via `params`, never glued into the `sql`
        string with f-strings or +. The database driver sends them separately
        from the query text, so a value can never be mistaken for a command.
        Building SQL by string concatenation is how SQL-injection attacks
        happen: a "name" of `'; DROP TABLE users; --` would otherwise be
        executed rather than stored.
    """
    with cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def query_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    """Run a query and return only the first row.

    Used when at most one row can match, typically a lookup by id or email.

    Returns:
        The row as a dictionary, or None when nothing matched. Callers should
        treat None as "does not exist" and usually raise NotFoundError.
    """
    with cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def execute(sql: str, params: tuple[Any, ...] = ()) -> None:
    """Run a statement that produces no rows, such as CREATE TABLE or DELETE.

    Because the connection is in autocommit mode, the change is saved as soon
    as this returns.
    """
    with cursor() as cur:
        cur.execute(sql, params)


def server_version() -> str:
    """Ask PostgreSQL to describe itself, and return the answer.

    `SELECT version()` is a built-in PostgreSQL function returning a sentence
    like "PostgreSQL 17.7 on x86_64-pc-linux-gnu ...".

    This exists for the health check. The point is not the version number
    itself — it is that getting an answer PROVES the entire chain works: the
    Lambda started, found its environment variables, reached the database over
    the network, authenticated, and ran a statement. If any link were broken
    this call would fail. On AWS, seeing "Aurora" in the reply confirms we are
    genuinely talking to the cloud database and not something local.

    Returns:
        The server's version string, or "unknown" if the query somehow returns
        no rows.
    """
    row = query_one("SELECT version() AS version")
    return row["version"] if row else "unknown"
