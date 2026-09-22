"""End-to-end tests of the authentication endpoints.

Every test here goes through the real Lambda handler, so it exercises the
complete path: event parsing, URL prefix stripping, routing, the authentication
and role gate in the router, the handler itself, the database, and error
formatting on the way back out.

That matters most for the permission tests. Calling a handler function directly
would skip the router — and the router is precisely where authentication and
authorization happen.
"""

import conftest

from app import db, security


class TestRegistration:
    def test_employee_can_register_and_is_signed_in(self, invoke, unique_email):
        status, body = invoke(
            "POST",
            "/api/v1/auth/register",
            {"full_name": "Dana Patel", "email": unique_email, "password": "GoodPassw0rd"},
        )

        assert status == 201
        assert body["user"]["email"] == unique_email
        assert body["user"]["full_name"] == "Dana Patel"
        # Self-registration must always produce an ordinary employee.
        assert body["user"]["role"] == security.ROLE_EMPLOYEE
        # A token comes back so the browser does not have to log in separately.
        assert body["token"]

    def test_password_hash_is_never_returned(self, invoke, unique_email):
        """The API must not leak the stored hash under any key."""
        _, body = invoke(
            "POST",
            "/api/v1/auth/register",
            {"full_name": "Dana Patel", "email": unique_email, "password": "GoodPassw0rd"},
        )

        assert "password_hash" not in body["user"]
        assert "password" not in body["user"]
        assert "GoodPassw0rd" not in str(body)

    def test_password_is_stored_hashed_not_plaintext(self, invoke, unique_email):
        """Check the database directly — the password must not be recoverable."""
        invoke(
            "POST",
            "/api/v1/auth/register",
            {"full_name": "Dana Patel", "email": unique_email, "password": "GoodPassw0rd"},
        )

        row = db.query_one("SELECT password_hash FROM users WHERE email = %s", (unique_email,))

        assert row["password_hash"] != "GoodPassw0rd"
        assert row["password_hash"].startswith("pbkdf2_sha256$")
        assert security.verify_password("GoodPassw0rd", row["password_hash"]) is True

    def test_non_acme_email_is_rejected_by_the_backend(self, invoke):
        """The domain rule must hold even when the browser is bypassed entirely."""
        status, body = invoke(
            "POST",
            "/api/v1/auth/register",
            {"full_name": "Outside Person", "email": "someone@gmail.com", "password": "GoodPassw0rd"},
        )

        assert status == 400
        assert body["error"] == "validation_error"
        assert "acme.inc" in body["message"]

    def test_lookalike_domain_is_rejected(self, invoke):
        """A domain that merely contains "acme.inc" must not be accepted."""
        status, _ = invoke(
            "POST",
            "/api/v1/auth/register",
            {"full_name": "Attacker", "email": "evil@acme.inc.attacker.com", "password": "GoodPassw0rd"},
        )

        assert status == 400

    def test_duplicate_email_is_rejected(self, invoke, registered_user):
        """Registering an address that already exists must return 409."""
        status, body = invoke(
            "POST",
            "/api/v1/auth/register",
            {
                "full_name": "Someone Else",
                "email": registered_user["email"],
                "password": "AnotherPassw0rd",
            },
        )

        assert status == 409
        assert body["error"] == "conflict"

    def test_duplicate_email_is_rejected_case_insensitively(self, invoke, registered_user):
        """UPPERCASE@acme.inc and uppercase@acme.inc are the same person."""
        status, _ = invoke(
            "POST",
            "/api/v1/auth/register",
            {
                "full_name": "Someone Else",
                "email": registered_user["email"].upper(),
                "password": "AnotherPassw0rd",
            },
        )

        assert status == 409

    def test_cannot_self_register_as_facility_admin(self, invoke, unique_email):
        """THE KEY PRIVILEGE-ESCALATION TEST.

        A request that asks for an elevated role must produce an ordinary
        employee, not an administrator.
        """
        status, body = invoke(
            "POST",
            "/api/v1/auth/register",
            {
                "full_name": "Ambitious Person",
                "email": unique_email,
                "password": "GoodPassw0rd",
                "role": security.ROLE_FACILITY_ADMIN,
            },
        )

        assert status == 201
        assert body["user"]["role"] == security.ROLE_EMPLOYEE

        # Confirm in the database too, not merely in the response.
        row = db.query_one("SELECT role FROM users WHERE email = %s", (unique_email,))
        assert row["role"] == security.ROLE_EMPLOYEE

    def test_cannot_self_register_as_engineer(self, invoke, unique_email):
        _, body = invoke(
            "POST",
            "/api/v1/auth/register",
            {
                "full_name": "Ambitious Person",
                "email": unique_email,
                "password": "GoodPassw0rd",
                "role": security.ROLE_ENGINEER,
            },
        )

        assert body["user"]["role"] == security.ROLE_EMPLOYEE

    def test_short_password_is_rejected(self, invoke, unique_email):
        status, body = invoke(
            "POST",
            "/api/v1/auth/register",
            {"full_name": "Dana Patel", "email": unique_email, "password": "short"},
        )

        assert status == 400
        assert body["details"]["field"] == "password"

    def test_missing_name_is_rejected(self, invoke, unique_email):
        status, body = invoke(
            "POST",
            "/api/v1/auth/register",
            {"email": unique_email, "password": "GoodPassw0rd"},
        )

        assert status == 400
        assert body["details"]["field"] == "full_name"

    def test_blank_name_is_rejected(self, invoke, unique_email):
        status, _ = invoke(
            "POST",
            "/api/v1/auth/register",
            {"full_name": "   ", "email": unique_email, "password": "GoodPassw0rd"},
        )

        assert status == 400


class TestLogin:
    def test_correct_credentials_return_a_token(self, invoke, registered_user):
        status, body = invoke(
            "POST",
            "/api/v1/auth/login",
            {"email": registered_user["email"], "password": registered_user["password"]},
        )

        assert status == 200
        assert body["token"]
        assert body["user"]["email"] == registered_user["email"]
        assert "password_hash" not in body["user"]

    def test_email_is_case_insensitive_at_login(self, invoke, registered_user):
        status, _ = invoke(
            "POST",
            "/api/v1/auth/login",
            {"email": registered_user["email"].upper(), "password": registered_user["password"]},
        )

        assert status == 200

    def test_wrong_password_is_rejected(self, invoke, registered_user):
        status, body = invoke(
            "POST",
            "/api/v1/auth/login",
            {"email": registered_user["email"], "password": "NotTheRightOne1"},
        )

        assert status == 401
        assert body["error"] == "unauthorized"

    def test_unknown_email_is_rejected(self, invoke):
        status, _ = invoke(
            "POST",
            "/api/v1/auth/login",
            {"email": "nobody+pytest-missing@acme.inc", "password": "AnyPassw0rd"},
        )

        assert status == 401

    def test_unknown_email_and_wrong_password_give_identical_replies(
        self, invoke, registered_user
    ):
        """Account enumeration guard.

        If these two responses differed, anyone could discover which employees
        have accounts by watching which error came back.
        """
        _, wrong_password = invoke(
            "POST",
            "/api/v1/auth/login",
            {"email": registered_user["email"], "password": "NotTheRightOne1"},
        )
        _, unknown_email = invoke(
            "POST",
            "/api/v1/auth/login",
            {"email": "nobody+pytest-missing@acme.inc", "password": "NotTheRightOne1"},
        )

        assert wrong_password == unknown_email

    def test_missing_fields_are_rejected(self, invoke):
        status, _ = invoke("POST", "/api/v1/auth/login", {"email": "someone@acme.inc"})
        assert status == 401

    def test_seeded_administrator_can_sign_in(self, invoke):
        """The bootstrap admin must work.

        Without it there would be no FACILITY_ADMIN in the system at all, since
        self-registration only ever creates employees.

        The password comes from the environment (conftest sets a throwaway value
        for the suite), never from a literal in the repository.
        """
        status, body = invoke(
            "POST",
            "/api/v1/auth/login",
            {
                "email": security.SEED_ADMIN_EMAIL,
                "password": conftest.BOOTSTRAP_ADMIN_TEST_PASSWORD,
            },
        )

        assert status == 200
        assert body["user"]["role"] == security.ROLE_FACILITY_ADMIN


class TestCurrentUser:
    def test_requires_a_token(self, invoke):
        """The central gate in the router must refuse anonymous callers."""
        status, body = invoke("GET", "/api/v1/auth/me")

        assert status == 401
        assert body["error"] == "unauthorized"

    def test_rejects_a_malformed_authorization_header(self, invoke, registered_user):
        import json

        from function import handler

        event = {
            "requestContext": {"http": {"method": "GET", "path": "/api/v1/auth/me"}},
            # Missing the "Bearer " prefix.
            "headers": {"authorization": registered_user["token"]},
            "body": None,
        }
        response = handler(event)

        assert response["statusCode"] == 401
        assert json.loads(response["body"])["error"] == "unauthorized"

    def test_rejects_a_tampered_token(self, invoke, registered_user):
        broken = registered_user["token"][:-4] + "AAAA"
        status, _ = invoke("GET", "/api/v1/auth/me", token=broken)

        assert status == 401

    def test_returns_the_signed_in_user(self, invoke, registered_user):
        status, body = invoke("GET", "/api/v1/auth/me", token=registered_user["token"])

        assert status == 200
        assert body["user"]["email"] == registered_user["email"]
        assert body["user"]["role"] == security.ROLE_EMPLOYEE
        assert "password_hash" not in body["user"]

    def test_deactivated_account_is_refused_immediately(self, invoke, registered_user):
        """Proves the role and status are re-read from the database.

        The token is still perfectly valid and unexpired. If the router trusted
        the token's contents instead of looking the user up, a deactivated
        person would keep access for up to twelve hours.
        """
        db.execute(
            "UPDATE users SET is_active = FALSE WHERE email = %s", (registered_user["email"],)
        )

        status, _ = invoke("GET", "/api/v1/auth/me", token=registered_user["token"])

        assert status == 401


class TestRoutingAndHealthStillWork:
    def test_health_is_still_public_and_working(self, invoke):
        """Slice 0 behaviour must survive the addition of authentication."""
        status, body = invoke("GET", "/api/v1/health")

        assert status == 200
        assert body["ok"] is True
        # Migration 2 has been added, so the schema should now report 2.
        assert body["schema_version"] >= 2

    def test_local_proxy_style_path_also_works(self, invoke):
        """The dev proxy strips the /api/v1 prefix; CloudFront does not."""
        status, _ = invoke("GET", "/health")
        assert status == 200

    def test_unknown_endpoint_is_404(self, invoke):
        status, body = invoke("GET", "/api/v1/nonexistent")

        assert status == 404
        assert body["error"] == "not_found"

    def test_wrong_method_is_405(self, invoke):
        status, body = invoke("GET", "/api/v1/auth/login")

        assert status == 405
        assert body["error"] == "method_not_allowed"
