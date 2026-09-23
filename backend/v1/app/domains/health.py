"""The health endpoint: evidence that the deployment actually works."""

from .. import db, migrations
from ..http import Request, ok


def get_health(request: Request) -> dict:
    """Report whether the service can reach and use its database.

    Deliberately runs a real query rather than returning a static "ok".
    Answering without touching the database would only prove the Lambda
    started, which is the easy part; a successful query also proves VPC
    networking, credentials, TLS and migrations are right. That is why this was
    the first endpoint built and deployed.

    Args:
        request: Unused — a health check takes no input, but the signature
            matches every other handler so the router can call them alike.

    Returns:
        200 with the database version (mentions Aurora when deployed), whether
        this is the local or AWS environment, and the applied schema version so
        a deployment that failed to migrate is visible.
    """
    # A failure here raises and becomes a 500, which is correct: a service that
    # cannot reach its database is not healthy and must not claim to be.
    database_version = db.server_version()

    return ok(
        {
            "ok": True,
            "database": database_version,
            "environment": "local" if db.is_local() else "aws",
            "schema_version": migrations.current_version(),
        }
    )
