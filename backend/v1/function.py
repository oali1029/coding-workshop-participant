"""The Lambda entry point — the very first code AWS runs for every request.

=============================================================================
WHY THIS FILE HAS THIS EXACT NAME AND LOCATION
=============================================================================
Neither the filename nor the function name below is a free choice.

The project's infrastructure (infra/locals.tf) scans the `backend/` folder and
automatically turns every sub-folder into a Lambda. For Python services it
hard-codes the entry point as `function.handler`, meaning:

    "in a file called function.py, call the function called handler"

So `backend/v1/function.py` must exist, and must define `handler`. Renaming
either breaks the deployment with an unhelpful error.

There is a second, separate requirement. The infrastructure DISCOVERS a Python
service by looking for `requirements.txt`, not for `function.py`. The
development script `bin/start-dev.sh` does the opposite — it counts services by
looking for `function.py`. The two disagree, which means BOTH files must be
present in this folder. With only `requirements.txt` the service deploys but the
local tooling cannot see it; with only `function.py` it is never deployed at all.

=============================================================================
WHERE THIS SITS IN THE REQUEST FLOW
=============================================================================
    React → CloudFront (or local proxy) → **THIS FILE** → router → handler
          → db.py → PostgreSQL → back out through this file → React

This file is deliberately thin. It does four things and delegates everything
else:

    1. Runs database migrations, once per Lambda startup.
    2. Answers browser CORS preflight checks.
    3. Passes the request to the router.
    4. Catches every possible error and turns it into a sensible HTTP reply.

=============================================================================
COLD STARTS: WHY SOME CODE LIVES OUTSIDE THE HANDLER
=============================================================================
AWS does not run our program from scratch for every request. It loads the file
once, then calls `handler` repeatedly for as long as requests keep arriving.

  * Code at the bottom of this file, outside any function, runs ONCE per
    loaded copy. That first slow request is called a "cold start".
  * Code inside `handler` runs on EVERY request.

We exploit this with the `_MIGRATIONS_DONE` flag: migrations are attempted on
the first request a given copy handles, then skipped for all the rest.
"""

import json
import logging
from typing import Any

from app import http, migrations
from app.errors import AppError
from app.router import dispatch

# Lambda automatically forwards anything logged here to CloudWatch, AWS's log
# service. `logging` is used rather than `print` because it records severity
# and timestamps, which makes filtering for errors in a busy log possible.
#
# The level is set on the root logger because AWS installs its own handler
# before our code runs; configuring ours here ensures INFO messages are not
# silently discarded.
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Whether migrations have already run in THIS copy of the program. See the
# cold-start explanation in the module docstring.
_MIGRATIONS_DONE = False


def _ensure_migrations() -> None:
    """Prepare the database, at most once per Lambda copy.

    Two steps, in order:
      1. Apply any outstanding schema migrations.
      2. Create the bootstrap administrator if it is missing and a password was
         supplied via the environment.

    Step 2 is separate from the migrations on purpose. Its password comes from
    an environment variable that may not be set, and a one-time migration that
    silently skipped the account would never get another chance to create it.
    Running it on each startup makes it self-healing — see
    migrations.ensure_bootstrap_admin.

    Runs on the first request each copy handles. Later requests to the same
    warm copy skip it, because a database round trip on every single request
    purely to confirm nothing has changed would be wasteful.

    Raises:
        Exception: Whatever the migration failed with. This is deliberately
            NOT swallowed: if the schema is wrong, every endpoint would fail
            in confusing ways. Failing loudly here makes the real cause
            obvious in the logs.
    """
    global _MIGRATIONS_DONE

    if _MIGRATIONS_DONE:
        return

    version = migrations.run_migrations()
    logger.info("Database schema is at version %s", version)

    # Never raises for a missing password — it logs a warning and moves on, so
    # the absence of an optional admin account cannot take the whole API down.
    migrations.ensure_bootstrap_admin()

    # Set only AFTER success. If migration raises, the flag stays False so the
    # next request retries — which matters because the failure may simply be
    # that Aurora was still waking up.
    _MIGRATIONS_DONE = True


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Handle one HTTP request. This is what AWS calls.

    Args:
        event: The request, as a dictionary. Its shape is decoded by
            app/http.py — see that file for what AWS actually sends.
        context: AWS runtime information such as remaining execution time.
            Unused here, but part of the signature AWS requires, so it is
            accepted and given a default so tests can omit it.

    Returns:
        A dictionary with "statusCode", "headers" and "body" keys. AWS turns
        this into the real HTTP response. Returning any other shape produces a
        502 error, because AWS cannot interpret it.
    """
    try:
        request = http.parse_request(event)

        # --- CORS preflight -------------------------------------------------
        # Before a browser sends a PATCH or DELETE to a different domain, it
        # first sends an OPTIONS request asking "am I allowed?". If the answer
        # is wrong the browser blocks the real request and the user sees a
        # confusing CORS error.
        #
        # We answer immediately with 204 (success, no content) and go no
        # further: a preflight is a permission question, not a real request, so
        # it must never reach the router or touch the database.
        #
        # The permissive headers come from app/http.py. The Lambda Function URL
        # is separately configured with open CORS by Terraform, and the local
        # proxy adds its own headers, so this mainly covers direct calls to the
        # function's own URL.
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
        # An EXPECTED failure: not found, forbidden, invalid input. The message
        # was written for the user, so it is safe to send back as-is.
        # Logged at warning rather than error because this is normal operation,
        # not a malfunction — a 404 does not mean the server is broken.
        logger.warning("Request failed with %s: %s", exc.status, exc.message)
        return http.response(exc.status, exc.to_dict())

    except Exception:  # noqa: BLE001
        # An UNEXPECTED failure: a bug in our code, or the database being
        # unreachable. Catching everything is intentional here; letting the
        # exception escape would make AWS return a raw 502 with no useful
        # information and no log entry we control.
        #
        # `exc_info=True` writes the full traceback to CloudWatch so we can
        # diagnose it, while the response deliberately contains NO detail.
        # Sending the real message could leak table names, file paths or
        # credentials to whoever is probing the API.
        logger.error("Unhandled error while processing request", exc_info=True)
        return http.response(
            500,
            {
                "error": "internal_error",
                "message": "An unexpected error occurred. Please try again.",
            },
        )


# =============================================================================
# LOCAL DEBUGGING HELPER
# =============================================================================
# Running `python function.py` from this folder calls the handler directly with
# a fake health-check event, without AWS, Docker or the React app involved.
#
# This is the fastest way to check that the code imports cleanly and that the
# database connection settings are right. It needs the POSTGRES_* environment
# variables set, or it falls back to the local development defaults in db.py.
if __name__ == "__main__":
    fake_event = {
        "requestContext": {"http": {"method": "GET", "path": "/api/v1/health"}},
        "headers": {},
    }
    result = handler(fake_event)
    print(f"status: {result['statusCode']}")
    print(json.dumps(json.loads(result["body"] or "{}"), indent=2))
