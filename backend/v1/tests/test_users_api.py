"""Tests for the Facility Admin's user administration endpoints.

The important cases here are the negative ones: who is refused, and which role
changes are rejected. Role management is the only way an ENGINEER can come into
existence, so its guards are worth testing thoroughly.
"""

from app import db, security


class TestListUsers:
    def test_admin_can_list_users(self, invoke, registered_user, admin_token):
        status, body = invoke("GET", "/api/v1/users", token=admin_token)

        assert status == 200
        emails = [user["email"] for user in body["users"]]
        assert registered_user["email"] in emails

    def test_password_hashes_are_never_returned(self, invoke, registered_user, admin_token):
        _, body = invoke("GET", "/api/v1/users", token=admin_token)

        assert "password_hash" not in str(body)

    def test_employee_is_refused(self, invoke, registered_user):
        status, body = invoke("GET", "/api/v1/users", token=registered_user["token"])

        assert status == 403
        assert body["error"] == "forbidden"

    def test_engineer_is_refused(self, invoke, engineer_user):
        """Engineers gain incident capabilities later, never user administration."""
        status, _ = invoke("GET", "/api/v1/users", token=engineer_user["token"])

        assert status == 403

    def test_requires_authentication(self, invoke):
        status, _ = invoke("GET", "/api/v1/users")

        assert status == 401


class TestChangeRole:
    def test_admin_can_promote_an_employee_to_engineer(
        self, invoke, registered_user, admin_token
    ):
        user_id = registered_user["user"]["id"]

        status, body = invoke(
            "PATCH", f"/api/v1/users/{user_id}/role", {"role": "ENGINEER"}, token=admin_token
        )

        assert status == 200
        assert body["user"]["role"] == security.ROLE_ENGINEER

        row = db.query_one("SELECT role FROM users WHERE id = %s", (user_id,))
        assert row["role"] == security.ROLE_ENGINEER

    def test_admin_can_demote_an_engineer_to_employee(self, invoke, engineer_user, admin_token):
        user_id = engineer_user["user"]["id"]

        status, body = invoke(
            "PATCH", f"/api/v1/users/{user_id}/role", {"role": "EMPLOYEE"}, token=admin_token
        )

        assert status == 200
        assert body["user"]["role"] == security.ROLE_EMPLOYEE

    def test_role_is_case_insensitive(self, invoke, registered_user, admin_token):
        user_id = registered_user["user"]["id"]

        _, body = invoke(
            "PATCH", f"/api/v1/users/{user_id}/role", {"role": "engineer"}, token=admin_token
        )

        assert body["user"]["role"] == security.ROLE_ENGINEER

    def test_promotion_takes_effect_without_signing_in_again(
        self, invoke, registered_user, admin_token
    ):
        """The role is re-read from the database on every request.

        The employee's existing token still says EMPLOYEE, but /auth/me reports
        the new role, which is what makes a promotion immediate.
        """
        user_id = registered_user["user"]["id"]
        invoke(
            "PATCH", f"/api/v1/users/{user_id}/role", {"role": "ENGINEER"}, token=admin_token
        )

        _, body = invoke("GET", "/api/v1/auth/me", token=registered_user["token"])

        assert body["user"]["role"] == security.ROLE_ENGINEER

    def test_cannot_promote_to_facility_admin(self, invoke, registered_user, admin_token):
        """Administrator accounts are managed separately, in a later slice."""
        user_id = registered_user["user"]["id"]

        status, body = invoke(
            "PATCH",
            f"/api/v1/users/{user_id}/role",
            {"role": "FACILITY_ADMIN"},
            token=admin_token,
        )

        assert status == 400
        assert body["details"]["field"] == "role"

        row = db.query_one("SELECT role FROM users WHERE id = %s", (user_id,))
        assert row["role"] == security.ROLE_EMPLOYEE

    def test_cannot_change_an_administrator(self, invoke, admin_token):
        """Also prevents an admin demoting themselves and locking everyone out.

        The caller is always an admin, so refusing admin targets covers the
        self-demotion case without a separate rule.
        """
        admin = db.query_one(
            "SELECT id FROM users WHERE email = %s", (security.SEED_ADMIN_EMAIL,)
        )

        status, body = invoke(
            "PATCH", f"/api/v1/users/{admin['id']}/role", {"role": "EMPLOYEE"}, token=admin_token
        )

        assert status == 403
        assert body["error"] == "forbidden"

        row = db.query_one("SELECT role FROM users WHERE id = %s", (admin["id"],))
        assert row["role"] == security.ROLE_FACILITY_ADMIN

    def test_unknown_role_is_rejected(self, invoke, registered_user, admin_token):
        user_id = registered_user["user"]["id"]

        status, body = invoke(
            "PATCH", f"/api/v1/users/{user_id}/role", {"role": "WIZARD"}, token=admin_token
        )

        assert status == 400
        assert body["details"]["field"] == "role"

    def test_missing_role_is_rejected(self, invoke, registered_user, admin_token):
        user_id = registered_user["user"]["id"]

        status, body = invoke("PATCH", f"/api/v1/users/{user_id}/role", {}, token=admin_token)

        assert status == 400
        assert body["details"]["field"] == "role"

    def test_unknown_user_is_not_found(self, invoke, admin_token):
        status, _ = invoke(
            "PATCH", "/api/v1/users/999999/role", {"role": "ENGINEER"}, token=admin_token
        )

        assert status == 404

    def test_non_numeric_id_is_not_found_rather_than_a_crash(self, invoke, admin_token):
        status, _ = invoke(
            "PATCH", "/api/v1/users/abc/role", {"role": "ENGINEER"}, token=admin_token
        )

        assert status == 404

    def test_employee_cannot_promote_themselves(self, invoke, registered_user):
        """The obvious privilege-escalation attempt must fail at the route gate."""
        user_id = registered_user["user"]["id"]

        status, _ = invoke(
            "PATCH",
            f"/api/v1/users/{user_id}/role",
            {"role": "ENGINEER"},
            token=registered_user["token"],
        )

        assert status == 403

        row = db.query_one("SELECT role FROM users WHERE id = %s", (user_id,))
        assert row["role"] == security.ROLE_EMPLOYEE

    def test_engineer_cannot_promote_anyone(self, invoke, engineer_user, registered_user):
        status, _ = invoke(
            "PATCH",
            f"/api/v1/users/{registered_user['user']['id']}/role",
            {"role": "ENGINEER"},
            token=engineer_user["token"],
        )

        assert status == 403


class TestEngineersKeepEmployeeCapabilities:
    """An engineer is an employee with extra permissions, not a different one."""

    def test_engineer_can_still_report_an_incident(self, invoke, engineer_user):
        status, body = invoke(
            "POST",
            "/api/v1/incidents",
            {"title": "My own broken chair", "description": "Wobbly.", "category": "FURNITURE"},
            token=engineer_user["token"],
        )

        assert status == 201
        assert body["incident"]["created_by"] == engineer_user["user"]["id"]

    def test_engineer_can_still_see_their_own_incidents(self, invoke, engineer_user):
        invoke(
            "POST",
            "/api/v1/incidents",
            {"title": "My own broken chair", "description": "Wobbly.", "category": "FURNITURE"},
            token=engineer_user["token"],
        )

        status, body = invoke("GET", "/api/v1/incidents", token=engineer_user["token"])

        assert status == 200
        assert len(body["incidents"]) == 1
        assert body["incidents"][0]["title"] == "My own broken chair"

    def test_a_demoted_engineer_keeps_the_incidents_they_reported(
        self, invoke, engineer_user, admin_token
    ):
        invoke(
            "POST",
            "/api/v1/incidents",
            {"title": "Reported while an engineer", "description": "x", "category": "OTHER"},
            token=engineer_user["token"],
        )

        invoke(
            "PATCH",
            f"/api/v1/users/{engineer_user['user']['id']}/role",
            {"role": "EMPLOYEE"},
            token=admin_token,
        )

        _, body = invoke("GET", "/api/v1/incidents", token=engineer_user["token"])

        assert [i["title"] for i in body["incidents"]] == ["Reported while an engineer"]
