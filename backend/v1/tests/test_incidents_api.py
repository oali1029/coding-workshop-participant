"""End-to-end tests for the incident endpoints.

These go through the real Lambda handler so the router's authentication and
role gate run too — calling a handler directly would skip them, and the
authorization behaviour is most of what is worth testing here.
"""

from app import db, security

VALID_INCIDENT = {
    "title": "Leaking tap in the third floor kitchen",
    "description": "Water pooling under the sink since this morning.",
    "category": "PLUMBING",
}


class TestCreateIncident:
    def test_employee_can_report_an_incident(self, invoke, registered_user):
        status, body = invoke(
            "POST", "/api/v1/incidents", VALID_INCIDENT, token=registered_user["token"]
        )

        assert status == 201
        incident = body["incident"]
        assert incident["title"] == VALID_INCIDENT["title"]
        assert incident["category"] == "PLUMBING"
        assert incident["id"]

    def test_new_incidents_always_start_open(self, invoke, registered_user):
        _, body = invoke(
            "POST", "/api/v1/incidents", VALID_INCIDENT, token=registered_user["token"]
        )

        assert body["incident"]["status"] == "OPEN"

    def test_client_cannot_choose_the_initial_status(self, invoke, registered_user):
        """A request asking for RESOLVED must still produce an OPEN incident."""
        _, body = invoke(
            "POST",
            "/api/v1/incidents",
            {**VALID_INCIDENT, "status": "RESOLVED"},
            token=registered_user["token"],
        )

        assert body["incident"]["status"] == "OPEN"

        row = db.query_one(
            "SELECT status FROM incidents WHERE id = %s", (body["incident"]["id"],)
        )
        assert row["status"] == "OPEN"

    def test_reporter_comes_from_the_token_not_the_body(self, invoke, registered_user):
        """Supplying someone else's user id must not change the reporter."""
        _, body = invoke(
            "POST",
            "/api/v1/incidents",
            {**VALID_INCIDENT, "created_by": 99999},
            token=registered_user["token"],
        )

        assert body["incident"]["created_by"] == registered_user["user"]["id"]

    def test_priority_defaults_to_medium(self, invoke, registered_user):
        _, body = invoke(
            "POST", "/api/v1/incidents", VALID_INCIDENT, token=registered_user["token"]
        )

        assert body["incident"]["priority"] == "MEDIUM"

    def test_priority_can_be_chosen(self, invoke, registered_user):
        _, body = invoke(
            "POST",
            "/api/v1/incidents",
            {**VALID_INCIDENT, "priority": "HIGH"},
            token=registered_user["token"],
        )

        assert body["incident"]["priority"] == "HIGH"

    def test_category_and_priority_are_case_insensitive(self, invoke, registered_user):
        _, body = invoke(
            "POST",
            "/api/v1/incidents",
            {**VALID_INCIDENT, "category": "hvac", "priority": "low"},
            token=registered_user["token"],
        )

        assert body["incident"]["category"] == "HVAC"
        assert body["incident"]["priority"] == "LOW"

    def test_location_is_optional(self, invoke, registered_user):
        _, body = invoke(
            "POST", "/api/v1/incidents", VALID_INCIDENT, token=registered_user["token"]
        )

        assert body["incident"]["location"] is None

    def test_blank_location_is_stored_as_null(self, invoke, registered_user):
        _, body = invoke(
            "POST",
            "/api/v1/incidents",
            {**VALID_INCIDENT, "location": "   "},
            token=registered_user["token"],
        )

        assert body["incident"]["location"] is None

    def test_location_is_kept_when_given(self, invoke, registered_user):
        _, body = invoke(
            "POST",
            "/api/v1/incidents",
            {**VALID_INCIDENT, "location": "Building A, 3rd floor"},
            token=registered_user["token"],
        )

        assert body["incident"]["location"] == "Building A, 3rd floor"

    def test_missing_title_is_rejected(self, invoke, registered_user):
        payload = {k: v for k, v in VALID_INCIDENT.items() if k != "title"}
        status, body = invoke("POST", "/api/v1/incidents", payload, token=registered_user["token"])

        assert status == 400
        assert body["details"]["field"] == "title"

    def test_missing_description_is_rejected(self, invoke, registered_user):
        payload = {k: v for k, v in VALID_INCIDENT.items() if k != "description"}
        status, body = invoke("POST", "/api/v1/incidents", payload, token=registered_user["token"])

        assert status == 400
        assert body["details"]["field"] == "description"

    def test_unknown_category_is_rejected(self, invoke, registered_user):
        status, body = invoke(
            "POST",
            "/api/v1/incidents",
            {**VALID_INCIDENT, "category": "TELEPORTER"},
            token=registered_user["token"],
        )

        assert status == 400
        assert body["details"]["field"] == "category"

    def test_unknown_priority_is_rejected(self, invoke, registered_user):
        status, body = invoke(
            "POST",
            "/api/v1/incidents",
            {**VALID_INCIDENT, "priority": "YESTERDAY"},
            token=registered_user["token"],
        )

        assert status == 400
        assert body["details"]["field"] == "priority"

    def test_requires_authentication(self, invoke):
        status, body = invoke("POST", "/api/v1/incidents", VALID_INCIDENT)

        assert status == 401
        assert body["error"] == "unauthorized"


class TestListMyIncidents:
    def test_returns_only_incidents_i_reported(self, invoke, registered_user, second_user):
        """The core authorization rule for the list endpoint."""
        invoke(
            "POST",
            "/api/v1/incidents",
            {**VALID_INCIDENT, "title": "Mine"},
            token=registered_user["token"],
        )
        invoke(
            "POST",
            "/api/v1/incidents",
            {**VALID_INCIDENT, "title": "Theirs"},
            token=second_user["token"],
        )

        _, body = invoke("GET", "/api/v1/incidents", token=registered_user["token"])

        titles = [incident["title"] for incident in body["incidents"]]
        assert "Mine" in titles
        assert "Theirs" not in titles
        assert all(
            incident["created_by"] == registered_user["user"]["id"]
            for incident in body["incidents"]
        )

    def test_newest_first(self, invoke, registered_user):
        invoke(
            "POST",
            "/api/v1/incidents",
            {**VALID_INCIDENT, "title": "Older"},
            token=registered_user["token"],
        )
        invoke(
            "POST",
            "/api/v1/incidents",
            {**VALID_INCIDENT, "title": "Newer"},
            token=registered_user["token"],
        )

        _, body = invoke("GET", "/api/v1/incidents", token=registered_user["token"])

        assert body["incidents"][0]["title"] == "Newer"

    def test_empty_for_a_user_with_no_incidents(self, invoke, second_user):
        _, body = invoke("GET", "/api/v1/incidents", token=second_user["token"])

        assert body["incidents"] == []

    def test_requires_authentication(self, invoke):
        status, _ = invoke("GET", "/api/v1/incidents")

        assert status == 401


class TestIncidentDetail:
    def test_can_open_my_own_incident(self, invoke, registered_user):
        _, made = invoke(
            "POST", "/api/v1/incidents", VALID_INCIDENT, token=registered_user["token"]
        )
        incident_id = made["incident"]["id"]

        status, body = invoke(
            "GET", f"/api/v1/incidents/{incident_id}", token=registered_user["token"]
        )

        assert status == 200
        assert body["incident"]["id"] == incident_id
        assert body["incident"]["description"] == VALID_INCIDENT["description"]

    def test_another_users_incident_is_not_found(self, invoke, registered_user, second_user):
        """404 rather than 403, so ids cannot be probed to learn what exists."""
        _, made = invoke(
            "POST", "/api/v1/incidents", VALID_INCIDENT, token=registered_user["token"]
        )
        incident_id = made["incident"]["id"]

        status, body = invoke(
            "GET", f"/api/v1/incidents/{incident_id}", token=second_user["token"]
        )

        assert status == 404
        assert body["error"] == "not_found"

    def test_an_admin_cannot_see_someone_elses_incident_in_this_slice(
        self, invoke, registered_user, admin_token
    ):
        """Every role is creator-scoped for Slice 2, including FACILITY_ADMIN.

        Organisation-wide visibility is a later slice; this test records the
        current rule so widening it later has to be a deliberate change.
        """
        _, made = invoke(
            "POST", "/api/v1/incidents", VALID_INCIDENT, token=registered_user["token"]
        )

        status, _ = invoke(
            "GET", f"/api/v1/incidents/{made['incident']['id']}", token=admin_token
        )

        assert status == 404

    def test_unknown_id_is_not_found(self, invoke, registered_user):
        status, _ = invoke("GET", "/api/v1/incidents/999999", token=registered_user["token"])

        assert status == 404

    def test_non_numeric_id_is_not_found_rather_than_a_crash(self, invoke, registered_user):
        status, _ = invoke("GET", "/api/v1/incidents/abc", token=registered_user["token"])

        assert status == 404

    def test_requires_authentication(self, invoke, registered_user):
        _, made = invoke(
            "POST", "/api/v1/incidents", VALID_INCIDENT, token=registered_user["token"]
        )

        status, _ = invoke("GET", f"/api/v1/incidents/{made['incident']['id']}")

        assert status == 401


class TestExistingBehaviourStillWorks:
    def test_health_still_reports_the_new_schema_version(self, invoke):
        status, body = invoke("GET", "/api/v1/health")

        assert status == 200
        assert body["schema_version"] >= 3

    def test_auth_me_still_works(self, invoke, registered_user):
        status, body = invoke("GET", "/api/v1/auth/me", token=registered_user["token"])

        assert status == 200
        assert body["user"]["role"] == security.ROLE_EMPLOYEE
