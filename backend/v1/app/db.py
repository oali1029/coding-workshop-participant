"""PostgreSQL access.

The same code runs against a local PostgreSQL and against Aurora on AWS. All
connection settings arrive as environment variables injected by Terraform
(``infra/locals.tf``), so the only real difference is TLS: Aurora requires it,
the local instance is not configured for it. See :func:`build_conninfo`.

Connection reuse: opening a connection is slow, especially the TLS handshake
against Aurora. Lambda keeps a loaded program in memory between requests, so
the connection is held in a module-level global and reused across warm
invocations. Because a pooled connection can go stale, :func:`cursor` discards
it on any failure and the next request reconnects.
"""

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

from psycopg import Connection, connect
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

_CONNECTION: Connection | None = None


def is_local() -> bool:
    """Whether we are running against LocalStack rather than real AWS.

    Terraform sets IS_LOCAL by checking the AWS account id; the local emulator
    always reports 000000000000.
    """
    return os.getenv("IS_LOCAL", "false").lower() == "true"


def build_conninfo() -> str:
    """Assemble the libpq connection string from injected environment variables.

    The defaults match local development so the module can be run directly; on
    AWS every value is supplied and the defaults are never reached.
    """
    parts = [
        f"host={os.getenv('POSTGRES_HOST', 'localhost')}",
        f"port={os.getenv('POSTGRES_PORT', '5432')}",
        f"user={os.getenv('POSTGRES_USER', 'postgres')}",
        f"password={os.getenv('POSTGRES_PASS', 'postgres123')}",
        f"dbname={os.getenv('POSTGRES_NAME', 'postgres')}",
        # Without a timeout an unreachable database would hang until the
        # Lambda's 300-second limit — slow to notice and expensive.
        "connect_timeout=15",
    ]

    # Aurora rejects unencrypted connections; the local instance rejects
    # encrypted ones. Asking for the wrong mode fails immediately, so this one
    # line is what lets a single codebase serve both.
    if not is_local():
        parts.append("sslmode=require")

    return " ".join(parts)


def get_connection() -> Connection:
    """Return the pooled connection, opening one if needed."""
    global _CONNECTION

    if _CONNECTION is None or _CONNECTION.closed:
        logger.info("Opening a new PostgreSQL connection")
        _CONNECTION = connect(
            build_conninfo(),
            # Rows as dicts rather than tuples, so code reads row["title"]
            # and survives a column being added.
            row_factory=dict_row,
            # A Lambda can be frozen between requests, and an open transaction
            # left behind would hold locks against other users. Code that needs
            # several statements to succeed together opens a transaction
            # explicitly instead — see migrations.py.
            autocommit=True,
        )
    return _CONNECTION


def reset_connection() -> None:
    """Discard the pooled connection so the next call reconnects.

    Called on any query failure. We cannot distinguish "that SQL was wrong"
    from "this connection is dead", and continuing to use a dead connection
    would fail every request until the Lambda is recycled.
    """
    global _CONNECTION

    if _CONNECTION is not None and not _CONNECTION.closed:
        try:
            _CONNECTION.close()
        except Exception:  # noqa: BLE001
            # Swallowed: we are already handling a failure, and an error while
            # tidying up must not replace the one the caller needs to see.
            logger.warning("Failed to close the PostgreSQL connection cleanly")

    _CONNECTION = None


@contextmanager
def cursor() -> Iterator[Any]:
    """Yield a cursor, discarding the pooled connection if anything fails.

    The original exception is re-raised unchanged; deciding whether a failure
    means "not found" or "server error" belongs to the handler.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            yield cur
    except Exception:
        reset_connection()
        raise


@contextmanager
def transaction() -> Iterator[Any]:
    """Yield a cursor whose statements all commit together, or not at all.

    The pooled connection is in autocommit mode, so each statement is normally
    its own transaction. Use this where two writes must not be observable
    apart — the block commits on exit and rolls back if anything raises.

    The connection is discarded on failure for the same reason as in
    :func:`cursor`: a connection whose state we are unsure of should not go
    back into the pool.
    """
    conn = get_connection()
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                yield cur
    except Exception:
        reset_connection()
        raise


def query_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Run a query and return all rows.

    Values must always be passed via ``params``, never interpolated into
    ``sql``. The driver sends them separately from the query text, so a value
    can never be executed as SQL.
    """
    with cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def query_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    """Run a query and return the first row, or None."""
    with cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def execute(sql: str, params: tuple[Any, ...] = ()) -> None:
    """Run a statement that returns no rows."""
    with cursor() as cur:
        cur.execute(sql, params)


def server_version() -> str:
    """Return the PostgreSQL version string.

    Used by the health check: getting an answer proves the whole chain works —
    environment variables, networking, credentials and TLS — rather than merely
    that the Lambda started.
    """
    row = query_one("SELECT version() AS version")
    return row["version"] if row else "unknown"
