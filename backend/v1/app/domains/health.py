"""The health check endpoint: proof that the whole system is wired up.

=============================================================================
WHAT THIS FILE IS RESPONSIBLE FOR
=============================================================================
This provides a single endpoint, `GET /api/v1/health`, whose only job is to
answer the question: "is this application actually working right now?"

It is the first thing we build and the first thing we deploy, before any
product feature exists at all.

=============================================================================
WHY A HEALTH CHECK IS WORTH BUILDING FIRST
=============================================================================
A great deal has to be correct before even the simplest feature can work:

    * Terraform has to notice our code and create a Lambda from it.
    * The upload has to include the psycopg library, or the program cannot
      even start.
    * CloudFront has to route "/api/v1/..." to the Lambda rather than trying
      to serve it as a web page.
    * The Lambda has to be allowed onto the network where the database lives.
    * The database password and hostname have to have been injected correctly.
    * The database has to accept an encrypted connection.
    * Our migrations have to run successfully.

If we built the whole product first and deployed at the end, a failure in ANY
of those would appear all at once, tangled together and very hard to diagnose.

By deploying this tiny endpoint first we test every one of those links in
isolation. Once `/api/v1/health` returns a real answer from the cloud, we know
the foundation is sound and every later feature is just business logic on top.

This is what the plan calls the "walking skeleton": something that walks the
entire path end to end, even though it does almost nothing useful yet.
"""

from .. import db, migrations
from ..http import Request, ok


def get_health(request: Request) -> dict:
    """Report whether the application can reach and use its database.

    Deliberately does real work rather than simply returning "ok". Replying
    without touching the database would tell us only that the Lambda started —
    which is the easy part. Running an actual query proves the hard parts:
    networking, credentials, and encryption.

    Args:
        request: The incoming request. Unused, because a health check takes no
            input. It is still accepted so that every handler in the
            application has the same shape and the router can call them all
            identically.

    Returns:
        A 200 response containing:
            ok               always True — reaching this line means the
                             database query above succeeded, since a failure
                             would have raised before getting here.
            database         PostgreSQL's own description of itself. On AWS
                             this should mention Aurora, which confirms we are
                             talking to the cloud database rather than
                             something local.
            environment      "local" or "aws", so we can tell at a glance
                             which deployment we are looking at.
            schema_version   which migration the database has reached, so a
                             deployment that failed to migrate is obvious.
    """
    # If the database is unreachable this raises, and the error handler in
    # ../function.py turns it into a 500. That is the correct outcome: an
    # application that cannot reach its database is not healthy, and must not
    # claim to be.
    database_version = db.server_version()

    return ok(
        {
            "ok": True,
            "database": database_version,
            "environment": "local" if db.is_local() else "aws",
            "schema_version": migrations.current_version(),
        }
    )
