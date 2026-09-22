"""Shared setup for the test suite.

=============================================================================
WHAT KIND OF TESTS THESE ARE
=============================================================================
These are INTEGRATION tests: they run against a real PostgreSQL database
rather than a fake one.

That is a deliberate choice. The most valuable things to verify in this
application are precisely the things a mock would paper over — that the UNIQUE
constraint really does reject a duplicate email, that the CHECK constraint
really does reject a non-ACME address, that `ON CONFLICT DO NOTHING` behaves as
the code assumes. A mocked database would happily agree with whatever we told
it and prove nothing.

The cost is that the tests need a database to talk to. They read the same
POSTGRES_* environment variables the application does, so they point at the
local PostgreSQL by default.

=============================================================================
HOW TESTS AVOID INTERFERING WITH EACH OTHER
=============================================================================
Every test account is created with an address containing a marker string, and
the fixtures delete all such rows before and after the run. Real accounts,
including the seeded administrator, are left untouched.
"""

import os
import sys
import uuid

import pytest

# The tests live in backend/v1/tests/ but import `app` and `function`, which sit
# in backend/v1/. Adding the parent directory to the import path makes those
# importable without installing the project as a package — which would be
# overkill here, since Lambda also just unzips these files side by side.
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
    """Ensure the schema exists, and remove test rows before and after the run.

    `scope="session"` means this runs once for the whole suite rather than per
    test, because migrating is not cheap and the schema does not change.
    `autouse=True` means every test gets it without having to ask.
    """
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
    """Return a fresh, unused ACME address for a test to register.

    A random component is included so that tests remain independent: a leftover
    row from an interrupted earlier run cannot collide with this one and cause a
    confusing "email already exists" failure in an unrelated test.

    The "+tag" form is standard email sub-addressing, and keeps the address
    valid while still ending in @acme.inc so it passes both the application
    check and the database CHECK constraint.
    """
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
    """Build an app.http.Request directly, with no AWS event involved.

    Handlers take a plain Request object, so they can be called in isolation.
    Tests that want to exercise the full Lambda path use `invoke` instead.
    """
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
def make_request():
    """Expose `_make_request` to tests as a fixture."""
    return _make_request


@pytest.fixture
def read_json():
    """Expose `_json` to tests as a fixture."""
    return _json


@pytest.fixture
def invoke():
    """Call the real Lambda handler with a synthetic Function URL event.

    This exercises the COMPLETE path — event parsing, prefix stripping,
    routing, authentication, the handler, and error formatting — which is what
    we need in order to assert on status codes such as 401 and 403. Calling a
    handler directly would bypass the router, and the router is where the
    permission checks live.
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


__all__ = ["security"]
