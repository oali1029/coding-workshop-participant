"""Shared test setup.

These are integration tests against a real PostgreSQL database. The behaviour
most worth verifying here is exactly what a mock would paper over — that the
UNIQUE constraint rejects duplicate emails, that the CHECK constraint rejects
non-ACME addresses, that ON CONFLICT DO NOTHING behaves as the code assumes.
They read the same POSTGRES_* variables as the application.

Test accounts all carry a marker in their email address so the fixtures can
clean up without touching real rows.
"""

import os
import sys
import uuid

import pytest

# Tests live in tests/ but import `app` and `function` from the parent, which
# Lambda also loads side by side rather than as an installed package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Point at the local database unless the environment already says otherwise.
# `setdefault` rather than plain assignment so a developer can aim the suite at
# a different database without editing this file.
os.environ.setdefault("IS_LOCAL", "true")
os.environ.setdefault("POSTGRES_HOST", "127.0.0.1")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASS", "postgres123")
os.environ.setdefault("POSTGRES_NAME", "postgres")

# A throwaway password for the bootstrap administrator, used ONLY by this test
# suite. It is deliberately obvious nonsense so nobody mistakes it for a real
# credential, and the real workshop password never appears in the repository.
#
# The tests assert against this variable rather than a literal, so the suite
# keeps passing whatever value an environment happens to supply.
BOOTSTRAP_ADMIN_TEST_PASSWORD = "pytest-only-not-a-real-password"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = BOOTSTRAP_ADMIN_TEST_PASSWORD

from app import db, migrations, security  # noqa: E402  (must follow the env setup above)

# Every address created by a test contains this, so cleanup can find them.
TEST_EMAIL_MARKER = "+pytest-"


@pytest.fixture(scope="session", autouse=True)
def prepared_database():
    """Migrate once per session, and clean test rows either side of the run."""
    migrations.run_migrations()

    # Remove any administrator left over from a previous run so that the account
    # is recreated with the test password set above. Without this, a database
    # seeded earlier with a different password would make the admin login test
    # fail for a reason that has nothing to do with the code under test.
    db.execute("DELETE FROM users WHERE email = %s", (security.SEED_ADMIN_EMAIL,))
    migrations.ensure_bootstrap_admin()

    _delete_test_users()

    yield  # the tests run at this point

    _delete_test_users()


def _delete_test_users() -> None:
    """Remove only the accounts this suite created."""
    db.execute("DELETE FROM users WHERE email LIKE %s", (f"%{TEST_EMAIL_MARKER}%",))


@pytest.fixture
def unique_email():
    """A fresh ACME address, randomised so a leftover row from an interrupted
    run cannot collide and fail an unrelated test."""
    return f"user{TEST_EMAIL_MARKER}{uuid.uuid4().hex[:10]}@acme.inc"


@pytest.fixture
def registered_user(unique_email):
    """Create an account and return its details plus a valid token.

    Used by tests that need to be signed in already, so they are not all
    repeating the registration steps.

    Returns:
        A dict with `email`, `password`, `token` and `user`.
    """
    from app.domains import auth

    password = "TestPassw0rd!"
    request = _make_request(
        "POST",
        "/auth/register",
        body={
            "full_name": "Test Person",
            "email": unique_email,
            "password": password,
        },
    )
    response = auth.register(request)
    payload = _json(response)

    return {
        "email": unique_email,
        "password": password,
        "token": payload["token"],
        "user": payload["user"],
    }


# ---------------------------------------------------------------------------
# Helpers shared by the test modules
# ---------------------------------------------------------------------------
def _make_request(method, path, body=None, headers=None):
    """Build a Request directly, bypassing the AWS event format."""
    from app.http import Request

    return Request(
        method=method,
        path=path,
        headers={k.lower(): v for k, v in (headers or {}).items()},
        body=body,
    )


def _json(response):
    """Decode the JSON body out of a Lambda-style response dictionary."""
    import json

    return json.loads(response["body"]) if response["body"] else None


@pytest.fixture
def invoke():
    """Call the real Lambda handler with a synthetic Function URL event.

    Exercises the full path including the router, which is where authentication
    and role checks happen — calling a handler directly would skip them.
    """
    from function import handler

    def _invoke(method, path, body=None, token=None):
        import json

        headers = {}
        if token:
            headers["authorization"] = f"Bearer {token}"

        event = {
            "requestContext": {"http": {"method": method, "path": path}},
            "headers": headers,
            "body": json.dumps(body) if body is not None else None,
        }
        response = handler(event)
        return response["statusCode"], _json(response)

    return _invoke
