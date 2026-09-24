"""Tests for the Facility Admin's organisation-wide incident list.

This endpoint is the prerequisite for assigning work in a later slice, and the
only place where one user sees another user's incidents — so who is refused
matters as much as what is returned.
"""

from conftest import incident_payload


class TestAdminIncidentList:
    def test_admin_sees_incidents_from_every_reporter(
        self, invoke, registered_user, second_user, admin_token
    ):
        invoke(
            "POST",
            "/api/v1/incidents",
            incident_payload(title="From the first user"),
            token=registered_user["token"],
        )
        invoke(
            "POST",
            "/api/v1/incidents",
            incident_payload(title="From the second user"),
            token=second_user["token"],
        )

        status, body = invoke("GET", "/api/v1/admin/incidents", token=admin_token)

        assert status == 200
        titles = [incident["title"] for incident in body["incidents"]]
        assert "From the first user" in titles
        assert "From the second user" in titles

    def test_includes_who_reported_each_incident(self, invoke, registered_user, admin_token):
        """Oversight is meaningless without knowing whose problem it is."""
        invoke("POST", "/api/v1/incidents", incident_payload(), token=registered_user["token"])

        _, body = invoke("GET", "/api/v1/admin/incidents", token=admin_token)

        mine = [
            incident
            for incident in body["incidents"]
            if incident["created_by"] == registered_user["user"]["id"]
        ]
        assert mine[0]["reporter_email"] == registered_user["email"]
        assert mine[0]["reporter_name"] == "Test Person"

    def test_newest_first(self, invoke, registered_user, admin_token):
        invoke(
            "POST",
            "/api/v1/incidents",
            incident_payload(title="Older"),
            token=registered_user["token"],
        )
        invoke(
            "POST",
            "/api/v1/incidents",
            incident_payload(title="Newer"),
            token=registered_user["token"],
        )

        _, body = invoke("GET", "/api/v1/admin/incidents", token=admin_token)

        assert body["incidents"][0]["title"] == "Newer"

    def test_never_returns_password_hashes_from_the_join(
        self, invoke, registered_user, admin_token
    ):
        """The reporter join reads the users table, so this is worth asserting."""
        invoke("POST", "/api/v1/incidents", incident_payload(), token=registered_user["token"])

        _, body = invoke("GET", "/api/v1/admin/incidents", token=admin_token)

        assert "password_hash" not in str(body)

    def test_employee_is_refused(self, invoke, registered_user):
        status, body = invoke("GET", "/api/v1/admin/incidents", token=registered_user["token"])

        assert status == 403
        assert body["error"] == "forbidden"

    def test_engineer_is_refused(self, invoke, engineer_user):
        """Engineers get a queue of assigned work later, not the whole list."""
        status, _ = invoke("GET", "/api/v1/admin/incidents", token=engineer_user["token"])

        assert status == 403

    def test_requires_authentication(self, invoke):
        status, _ = invoke("GET", "/api/v1/admin/incidents")

        assert status == 401


class TestMyIncidentsStaysCreatorScoped:
    """GET /incidents must keep meaning "incidents I reported" for every role.

    If it ever widened for admins, an admin would lose sight of their own
    reports among everyone else's.
    """

    def test_admin_my_incidents_excludes_other_peoples(
        self, invoke, registered_user, admin_token
    ):
        invoke(
            "POST",
            "/api/v1/incidents",
            incident_payload(title="Reported by an employee"),
            token=registered_user["token"],
        )

        _, body = invoke("GET", "/api/v1/incidents", token=admin_token)

        titles = [incident["title"] for incident in body["incidents"]]
        assert "Reported by an employee" not in titles
