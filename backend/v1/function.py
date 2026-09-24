"""Lambda entry point.

The filename and handler name are fixed by the infrastructure: Terraform turns
every folder under ``backend/`` into a Lambda and pins Python services to
``function.handler``. Note that it *discovers* a Python service by the presence
of ``requirements.txt`` while ``bin/start-dev.sh`` counts services by
``function.py`` — the two disagree, so both files must exist here.

This module stays thin: prepare the database once per cold start, answer CORS
preflights, delegate to the router, and convert anything raised into an HTTP
response.

Code at module level runs once per loaded copy (a "cold start"); code inside
``handler`` runs per request. ``_MIGRATIONS_DONE`` exploits that so the schema
check happens once rather than on every call.
"""

import json
import logging
from typing import Any

from app import demo_seed, http, migrations
from app.errors import AppError
from app.router import dispatch

# Lambda forwards this to CloudWatch. The level is set on the root logger
# because AWS installs its own handler before our code runs.
logger = logging.getLogger()
logger.setLevel(logging.INFO)

_MIGRATIONS_DONE = False


def _ensure_migrations() -> None:
    """Apply migrations and seed the bootstrap admin, once per Lambda copy.

    The admin step is separate from the migrations because its password comes
    from an environment variable that may be unset, and a one-time migration
    that skipped it would never retry. See migrations.ensure_bootstrap_admin.

    Migration failures are deliberately not swallowed: a wrong schema would
    make every endpoint fail confusingly, so it should be loud in the logs.
    """
    global _MIGRATIONS_DONE

    if _MIGRATIONS_DONE:
        return

    version = migrations.run_migrations()
    logger.info("Database schema is at version %s", version)

    # Never raises for a missing password — logs and continues, so an optional
    # account cannot take the API down.
    migrations.ensure_bootstrap_admin()

    # Set only after success, so a failure (Aurora still waking, say) is
    # retried by the next request.
    _MIGRATIONS_DONE = True


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Handle one HTTP request.

    Args:
        event: The request as a dictionary; decoded by ``app.http``.
        context: AWS runtime information. Unused, but part of the required
            signature; defaulted so tests can omit it.

    Returns:
        A dict with statusCode, headers and body. Any other shape produces a
        502, because AWS cannot interpret it.
    """
    # OPERATOR-ONLY PATH, CHECKED BEFORE THE EVENT IS READ AS A REQUEST.
    #
    # The demo seeder is reachable only by invoking this function directly
    # through the AWS API, which needs lambda:InvokeFunction and is therefore
    # gated by IAM. A Function URL request can never be classified as a direct
    # invocation: the Lambda service always adds requestContext, headers and
    # rawPath to an HTTP event, and a caller's JSON body arrives as the `body`
    # string rather than at the top level of the event. classify_event carries
    # the full argument; an event that somehow looks like both is refused here
    # rather than guessed at.
    #
    # Everything below this block is unchanged, so the HTTP path is exactly
    # what it was.
    verdict = demo_seed.classify_event(event)

    if verdict == demo_seed.EVENT_DIRECT:
        logger.info("Handling a direct demo-seed invocation")
        return demo_seed.handle_direct_invoke(event)

    if verdict == demo_seed.EVENT_AMBIGUOUS:
        logger.warning("Refused an event carrying both HTTP fields and the demo-seed marker")
        return http.response(
            400, {"error": "bad_request", "message": "This request could not be interpreted."}
        )

    try:
        request = http.parse_request(event)

        # A preflight is a permission question, not a real request, so it is
        # answered here and never reaches the router or the database.
        if request.method == "OPTIONS":
            return http.response(
                204,
                None,
                {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, Authorization",
                    "Access-Control-Max-Age": "86400",
                },
            )

        _ensure_migrations()

        return dispatch(request)

    except AppError as exc:
        # Expected failure. Its message was written for the user, and a 404 is
        # normal operation rather than a malfunction, hence warning not error.
        logger.warning("Request failed with %s: %s", exc.status, exc.message)
        return http.response(exc.status, exc.to_dict())

    except Exception:  # noqa: BLE001
        # Unexpected failure. Catching everything is intentional: letting it
        # escape would give AWS's own opaque 502 with no log we control. The
        # traceback goes to CloudWatch; the response deliberately carries no
        # detail, since the real message could expose table names or paths.
        logger.error("Unhandled error while processing request", exc_info=True)
        return http.response(
            500,
            {
                "error": "internal_error",
                "message": "An unexpected error occurred. Please try again.",
            },
        )


if __name__ == "__main__":
    # Quick local check that the code imports and the database settings work,
    # without AWS, Docker or the frontend. Uses the POSTGRES_* environment
    # variables, falling back to the local defaults in app/db.py.
    fake_event = {
        "requestContext": {"http": {"method": "GET", "path": "/api/v1/health"}},
        "headers": {},
    }
    result = handler(fake_event)
    print(f"status: {result['statusCode']}")
    print(json.dumps(json.loads(result["body"] or "{}"), indent=2))
