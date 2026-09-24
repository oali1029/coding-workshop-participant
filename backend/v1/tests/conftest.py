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

# Captured BEFORE the override below, because the suite shares one database with
# the running application. The tests reseed admin@acme.inc with the throwaway
# password above, and ensure_bootstrap_admin creates but never resets — so
# without restoring it afterwards the developer's own admin login would silently
# stop working until they deleted the row by hand.
DEVELOPER_BOOTSTRAP_PASSWORD = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD") or os.environ.get(
    "TF_VAR_aws_bootstrap_admin_password"
)

os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = BOOTSTRAP_ADMIN_TEST_PASSWORD

from app import db, migrations, security  # noqa: E402  (must follow the env setup above)

# Every address created by a test contains this, so cleanup can find them.
TEST_EMAIL_MARKER = "+pytest-"

# Buildings created by this suite carry this prefix so cleanup leaves real ones
# alone.
TEST_BUILDING_PREFIX = "pytest-building-"

# Ids of the building, floor and seat every incident test reports against.
# Populated by the session fixture below, then read by incident_payload().
TEST_FACILITY: dict[str, int] = {}


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
    _create_test_facility()

    yield  # the tests run at this point

    _delete_test_users()
    _delete_test_facilities()
    _restore_developer_admin()


def _restore_developer_admin() -> None:
    """Undo the suite's overwrite of admin@acme.inc.

    The account is removed either way, so a stale test password can never
    shadow the real one. When the developer has supplied a bootstrap password it
    is recreated immediately; otherwise the next application startup creates it.
    """
    db.execute(
        "DELETE FROM incidents WHERE created_by = (SELECT id FROM users WHERE email = %s)",
        (security.SEED_ADMIN_EMAIL,),
    )
    db.execute("DELETE FROM users WHERE email = %s", (security.SEED_ADMIN_EMAIL,))

    if DEVELOPER_BOOTSTRAP_PASSWORD:
        os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = DEVELOPER_BOOTSTRAP_PASSWORD
        migrations.ensure_bootstrap_admin()


def _create_test_facility() -> None:
    """Create the building, floor and seat that incident tests report against.

    Building and floor are required when reporting, so every incident test needs
    somewhere to point at. One shared facility keeps those tests about the
    behaviour they are actually checking.
    """
    building = db.query_one(
        "INSERT INTO buildings (name) VALUES (%s) RETURNING id",
        (f"{TEST_BUILDING_PREFIX}main",),
    )
    floor = db.query_one(
        "INSERT INTO floors (building_id, name) VALUES (%s, %s) RETURNING id",
        (building["id"], "Floor 1"),
    )
    seat = db.query_one(
        "INSERT INTO seats (floor_id, code) VALUES (%s, %s) RETURNING id",
        (floor["id"], "T-001"),
    )

    TEST_FACILITY.update(
        building_id=building["id"], floor_id=floor["id"], seat_id=seat["id"]
    )


def _delete_test_facilities() -> None:
    """Remove facilities this suite created. Floors and seats cascade."""
    db.execute(
        "DELETE FROM buildings WHERE name LIKE %s", (f"{TEST_BUILDING_PREFIX}%",)
    )


@pytest.fixture
def facility():
    """Ids of the shared test building, floor and seat."""
    return dict(TEST_FACILITY)


def incident_payload(**overrides):
    """Build a valid incident body, with the shared test facility filled in.

    A function rather than a module constant because TEST_FACILITY is only
    populated once the session fixture has run.
    """
    payload = {
        "title": "Broken air conditioning",
        "description": "Third floor is too warm.",
        "category": "HVAC",
        "building_id": TEST_FACILITY["building_id"],
        "floor_id": TEST_FACILITY["floor_id"],
    }
    payload.update(overrides)
    return payload


def _delete_test_users() -> None:
    """Remove the accounts this suite created, and anything referencing them.

    incidents.created_by is a foreign key with no ON DELETE rule, so PostgreSQL
    refuses to delete a user who still has incidents — deliberately, since
    incident history should outlive an account. Tests therefore clear their
    incidents first.
    """
    db.execute(
        """
        DELETE FROM incidents
        WHERE created_by IN (SELECT id FROM users WHERE email LIKE %s)
        """,
        (f"%{TEST_EMAIL_MARKER}%",),
    )
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


@pytest.fixture
def second_user(unique_email):
    """A different signed-in employee, for testing that users cannot see each
    other's data."""
    from app.domains import auth

    password = "OtherPassw0rd!"
    response = auth.register(
        _make_request(
            "POST",
            "/auth/register",
            body={
                "full_name": "Other Person",
                # unique_email is per-test, so prefix it to get a second
                # distinct address within the same test.
                "email": f"second-{unique_email}",
                "password": password,
            },
        )
    )
    payload = _json(response)

    return {"email": f"second-{unique_email}", "token": payload["token"], "user": payload["user"]}


@pytest.fixture
def engineer_user(unique_email):
    """A signed-in ENGINEER.

    Registration always produces an EMPLOYEE, so the role is set directly here
    rather than through the API — this fixture is used by tests of *other*
    endpoints, which should not depend on role management working.
    """
    from app.domains import auth

    email = f"engineer-{unique_email}"
    password = "EngineerPassw0rd!"

    auth.register(
        _make_request(
            "POST",
            "/auth/register",
            body={"full_name": "Engineer Person", "email": email, "password": password},
        )
    )
    db.execute(
        "UPDATE users SET role = %s WHERE email = %s", (security.ROLE_ENGINEER, email)
    )

    # Sign in after the promotion so the returned token reflects the new role.
    payload = _json(
        auth.login(
            _make_request("POST", "/auth/login", body={"email": email, "password": password})
        )
    )

    return {"email": email, "token": payload["token"], "user": payload["user"]}


@pytest.fixture
def admin_token():
    """A token for the seeded FACILITY_ADMIN.

    Used to confirm that admins are creator-scoped too in this slice.
    """
    from app.domains import auth

    response = auth.login(
        _make_request(
            "POST",
            "/auth/login",
            body={
                "email": security.SEED_ADMIN_EMAIL,
                "password": BOOTSTRAP_ADMIN_TEST_PASSWORD,
            },
        )
    )
    return _json(response)["token"]


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
