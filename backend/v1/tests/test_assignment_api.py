"""Tests for incident assignment and the engineer workflow.

The valuable cases here are the refusals: who may assign, who may set CLOSED,
and whether the three lists stay distinct. Those rules are the product, and a
mistake in them is invisible until someone sees work that is not theirs.
"""

from conftest import incident_payload

from app import db, security


def _report(invoke, token, title="Broken air conditioning"):
    """Report an incident and return its id."""
    _, body = invoke("POST", "/api/v1/incidents", incident_payload(title=title), token=token)
    return body["incident"]["id"]


def _assign(invoke, admin_token, incident_id, assignee_id):
    return invoke(
        "PATCH",
        f"/api/v1/incidents/{incident_id}",
        {"assignee_id": assignee_id},
        token=admin_token,
    )


class TestAssignment:
    def test_admin_can_assign_to_an_engineer(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        incident_id = _report(invoke, registered_user["token"])

        status, body = _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])

        assert status == 200
        assert body["incident"]["assignee_id"] == engineer_user["user"]["id"]
        assert body["incident"]["assignee_name"] == "Engineer Person"

    def test_assignment_does_not_change_status(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """Assigned and being-worked-on are separate facts."""
        incident_id = _report(invoke, registered_user["token"])

        _, body = _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])

        assert body["incident"]["status"] == "OPEN"

    def test_admin_can_reassign(self, invoke, registered_user, engineer_user, admin_token):
        incident_id = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])

        # Promote a second person so there is somewhere to reassign to.
        other_id = registered_user["user"]["id"]
        invoke(
            "PATCH", f"/api/v1/users/{other_id}/role", {"role": "ENGINEER"}, token=admin_token
        )

        status, body = _assign(invoke, admin_token, incident_id, other_id)

        assert status == 200
        assert body["incident"]["assignee_id"] == other_id

    def test_admin_can_unassign(self, invoke, registered_user, engineer_user, admin_token):
        incident_id = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])

        status, body = _assign(invoke, admin_token, incident_id, None)

        assert status == 200
        assert body["incident"]["assignee_id"] is None
        assert body["incident"]["assignee_name"] is None

    def test_cannot_assign_to_an_employee(
        self, invoke, registered_user, second_user, admin_token
    ):
        """Only ENGINEER may hold work — verified server-side, not by the dropdown."""
        incident_id = _report(invoke, registered_user["token"])

        status, body = _assign(invoke, admin_token, incident_id, second_user["user"]["id"])

        assert status == 400
        assert body["details"]["field"] == "assignee_id"

    def test_cannot_assign_to_an_admin(self, invoke, registered_user, admin_token):
        """Admins oversee work; they are never assignees."""
        incident_id = _report(invoke, registered_user["token"])
        admin = db.query_one(
            "SELECT id FROM users WHERE email = %s", (security.SEED_ADMIN_EMAIL,)
        )

        status, _ = _assign(invoke, admin_token, incident_id, admin["id"])

        assert status == 400

    def test_cannot_assign_to_an_inactive_engineer(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        incident_id = _report(invoke, registered_user["token"])
        db.execute(
            "UPDATE users SET is_active = FALSE WHERE id = %s", (engineer_user["user"]["id"],)
        )

        status, _ = _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])

        assert status == 400

    def test_cannot_assign_to_a_nonexistent_user(self, invoke, registered_user, admin_token):
        incident_id = _report(invoke, registered_user["token"])

        status, _ = _assign(invoke, admin_token, incident_id, 999999)

        assert status == 400

    def test_engineer_cannot_assign(self, invoke, registered_user, engineer_user, admin_token):
        """Reassignment is oversight, not fieldwork."""
        incident_id = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])

        status, body = invoke(
            "PATCH",
            f"/api/v1/incidents/{incident_id}",
            {"assignee_id": engineer_user["user"]["id"]},
            token=engineer_user["token"],
        )

        assert status == 403
        assert body["error"] == "forbidden"

    def test_a_refused_assignment_changes_nothing(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """An engineer sending status + assignee must not get the status applied."""
        incident_id = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])

        invoke(
            "PATCH",
            f"/api/v1/incidents/{incident_id}",
            {"status": "IN_PROGRESS", "assignee_id": 1},
            token=engineer_user["token"],
        )

        row = db.query_one("SELECT status FROM incidents WHERE id = %s", (incident_id,))
        assert row["status"] == "OPEN"

    def test_employee_cannot_patch_at_all(self, invoke, registered_user):
        incident_id = _report(invoke, registered_user["token"])

        status, _ = invoke(
            "PATCH",
            f"/api/v1/incidents/{incident_id}",
            {"status": "IN_PROGRESS"},
            token=registered_user["token"],
        )

        assert status == 403


class TestEngineerWorkflow:
    def test_engineer_can_progress_their_assigned_incident(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        incident_id = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])

        for status_value in ("IN_PROGRESS", "BLOCKED", "RESOLVED"):
            # BLOCKED must say why; the other transitions ignore the extra field.
            status, body = invoke(
                "PATCH",
                f"/api/v1/incidents/{incident_id}",
                {"status": status_value, "blocked_reason": "Waiting on a spare part."},
                token=engineer_user["token"],
            )
            assert status == 200
            assert body["incident"]["status"] == status_value

    def test_engineer_cannot_close(self, invoke, registered_user, engineer_user, admin_token):
        """CLOSED is the admin's acceptance of the work, not the engineer's."""
        incident_id = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])

        status, body = invoke(
            "PATCH",
            f"/api/v1/incidents/{incident_id}",
            {"status": "CLOSED"},
            token=engineer_user["token"],
        )

        assert status == 403
        assert body["error"] == "forbidden"

        row = db.query_one("SELECT status FROM incidents WHERE id = %s", (incident_id,))
        assert row["status"] == "OPEN"

    def test_engineer_cannot_touch_an_incident_assigned_to_someone_else(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """404, not 403 — we do not confirm the incident exists."""
        incident_id = _report(invoke, registered_user["token"])

        status, _ = invoke(
            "PATCH",
            f"/api/v1/incidents/{incident_id}",
            {"status": "IN_PROGRESS"},
            token=engineer_user["token"],
        )

        assert status == 404

    def test_engineer_cannot_reopen_a_closed_incident(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """The terminal guard: an admin's acceptance is not reversible by an engineer."""
        incident_id = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])
        invoke(
            "PATCH",
            f"/api/v1/incidents/{incident_id}",
            {"status": "CLOSED"},
            token=admin_token,
        )

        status, _ = invoke(
            "PATCH",
            f"/api/v1/incidents/{incident_id}",
            {"status": "IN_PROGRESS"},
            token=engineer_user["token"],
        )

        assert status == 403

        row = db.query_one("SELECT status FROM incidents WHERE id = %s", (incident_id,))
        assert row["status"] == "CLOSED"

    def test_engineer_can_open_their_assigned_incident(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """Assignment grants read access to an incident someone else reported."""
        incident_id = _report(invoke, registered_user["token"])

        before, _ = invoke(
            "GET", f"/api/v1/incidents/{incident_id}", token=engineer_user["token"]
        )
        assert before == 404

        _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])

        after, body = invoke(
            "GET", f"/api/v1/incidents/{incident_id}", token=engineer_user["token"]
        )
        assert after == 200
        assert body["incident"]["id"] == incident_id

    def test_invalid_status_is_rejected(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        incident_id = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])

        status, body = invoke(
            "PATCH",
            f"/api/v1/incidents/{incident_id}",
            {"status": "NEARLY_DONE"},
            token=engineer_user["token"],
        )

        assert status == 400
        assert body["details"]["field"] == "status"

    def test_empty_update_is_rejected(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        incident_id = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])

        status, _ = invoke(
            "PATCH", f"/api/v1/incidents/{incident_id}", {}, token=engineer_user["token"]
        )

        assert status == 400

    def test_updated_at_advances(self, invoke, registered_user, engineer_user, admin_token):
        """updated_at was frozen until this slice, because nothing updated an incident."""
        incident_id = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])

        before = db.query_one(
            "SELECT created_at, updated_at FROM incidents WHERE id = %s", (incident_id,)
        )

        invoke(
            "PATCH",
            f"/api/v1/incidents/{incident_id}",
            {"status": "IN_PROGRESS"},
            token=engineer_user["token"],
        )

        after = db.query_one("SELECT updated_at FROM incidents WHERE id = %s", (incident_id,))
        assert after["updated_at"] > before["created_at"]


class TestAdminReview:
    def test_admin_can_close_a_resolved_incident(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        incident_id = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])
        invoke(
            "PATCH",
            f"/api/v1/incidents/{incident_id}",
            {"status": "RESOLVED"},
            token=engineer_user["token"],
        )

        status, body = invoke(
            "PATCH",
            f"/api/v1/incidents/{incident_id}",
            {"status": "CLOSED"},
            token=admin_token,
        )

        assert status == 200
        assert body["incident"]["status"] == "CLOSED"

    def test_admin_can_send_resolved_work_back(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """Review can reject: back to OPEN or IN_PROGRESS for more work."""
        incident_id = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])
        invoke(
            "PATCH",
            f"/api/v1/incidents/{incident_id}",
            {"status": "RESOLVED"},
            token=engineer_user["token"],
        )

        status, body = invoke(
            "PATCH",
            f"/api/v1/incidents/{incident_id}",
            {"status": "IN_PROGRESS"},
            token=admin_token,
        )

        assert status == 200
        assert body["incident"]["status"] == "IN_PROGRESS"

    def test_admin_can_update_an_incident_assigned_to_nobody(
        self, invoke, registered_user, admin_token
    ):
        """Admins act on any incident without needing an assignment."""
        incident_id = _report(invoke, registered_user["token"])

        status, body = invoke(
            "PATCH",
            f"/api/v1/incidents/{incident_id}",
            {"status": "IN_PROGRESS"},
            token=admin_token,
        )

        assert status == 200
        assert body["incident"]["status"] == "IN_PROGRESS"

    def test_admin_can_reopen_a_closed_incident(
        self, invoke, registered_user, admin_token
    ):
        incident_id = _report(invoke, registered_user["token"])
        invoke(
            "PATCH", f"/api/v1/incidents/{incident_id}", {"status": "CLOSED"}, token=admin_token
        )

        status, body = invoke(
            "PATCH", f"/api/v1/incidents/{incident_id}", {"status": "OPEN"}, token=admin_token
        )

        assert status == 200
        assert body["incident"]["status"] == "OPEN"

    def test_unknown_incident_is_not_found(self, invoke, admin_token):
        status, _ = invoke(
            "PATCH", "/api/v1/incidents/999999", {"status": "OPEN"}, token=admin_token
        )

        assert status == 404


class TestTheThreeListsStaySeparate:
    """My Incidents, Assigned Incidents and All Incidents mean different things."""

    def test_assigned_queue_shows_only_assigned_work(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        assigned_id = _report(invoke, registered_user["token"], "Someone else reported this")
        _assign(invoke, admin_token, assigned_id, engineer_user["user"]["id"])
        _report(invoke, engineer_user["token"], "The engineer's own report")

        status, body = invoke("GET", "/api/v1/incidents/assigned", token=engineer_user["token"])

        assert status == 200
        titles = [incident["title"] for incident in body["incidents"]]
        assert titles == ["Someone else reported this"]

    def test_my_incidents_shows_only_what_i_reported(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        assigned_id = _report(invoke, registered_user["token"], "Someone else reported this")
        _assign(invoke, admin_token, assigned_id, engineer_user["user"]["id"])
        _report(invoke, engineer_user["token"], "The engineer's own report")

        _, body = invoke("GET", "/api/v1/incidents", token=engineer_user["token"])

        titles = [incident["title"] for incident in body["incidents"]]
        assert titles == ["The engineer's own report"]

    def test_an_incident_you_reported_and_were_assigned_appears_in_both(
        self, invoke, engineer_user, admin_token
    ):
        incident_id = _report(invoke, engineer_user["token"], "Reported and assigned to me")
        _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])

        _, mine = invoke("GET", "/api/v1/incidents", token=engineer_user["token"])
        _, queue = invoke("GET", "/api/v1/incidents/assigned", token=engineer_user["token"])

        assert [i["id"] for i in mine["incidents"]] == [incident_id]
        assert [i["id"] for i in queue["incidents"]] == [incident_id]

    def test_admin_has_no_assigned_queue(self, invoke, admin_token):
        """Admins are never assignees, so the route is closed to them."""
        status, body = invoke("GET", "/api/v1/incidents/assigned", token=admin_token)

        assert status == 403
        assert body["error"] == "forbidden"

    def test_employee_has_no_assigned_queue(self, invoke, registered_user):
        status, _ = invoke("GET", "/api/v1/incidents/assigned", token=registered_user["token"])

        assert status == 403

    def test_assigned_route_is_not_shadowed_by_the_id_route(self, invoke, engineer_user):
        """"/incidents/assigned" must not be parsed as incident id "assigned"."""
        status, body = invoke("GET", "/api/v1/incidents/assigned", token=engineer_user["token"])

        assert status == 200
        assert "incidents" in body

    def test_admin_all_incidents_shows_the_assignee(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        incident_id = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])

        _, body = invoke("GET", "/api/v1/admin/incidents", token=admin_token)

        match = [i for i in body["incidents"] if i["id"] == incident_id][0]
        assert match["assignee_name"] == "Engineer Person"

    def test_reporter_sees_progress_on_their_own_incident(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """The employee tracks the work without being able to change it."""
        incident_id = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])
        invoke(
            "PATCH",
            f"/api/v1/incidents/{incident_id}",
            {"status": "IN_PROGRESS"},
            token=engineer_user["token"],
        )

        _, body = invoke(
            "GET", f"/api/v1/incidents/{incident_id}", token=registered_user["token"]
        )

        assert body["incident"]["status"] == "IN_PROGRESS"
        assert body["incident"]["assignee_name"] == "Engineer Person"


class TestEngineerList:
    def test_admin_can_list_assignable_engineers(self, invoke, engineer_user, admin_token):
        status, body = invoke("GET", "/api/v1/engineers", token=admin_token)

        assert status == 200
        ids = [engineer["id"] for engineer in body["engineers"]]
        assert engineer_user["user"]["id"] in ids

    def test_employees_and_admins_are_not_listed(
        self, invoke, registered_user, admin_token
    ):
        _, body = invoke("GET", "/api/v1/engineers", token=admin_token)

        emails = [engineer["email"] for engineer in body["engineers"]]
        assert registered_user["email"] not in emails
        assert security.SEED_ADMIN_EMAIL not in emails

    def test_engineer_cannot_list_engineers(self, invoke, engineer_user):
        status, _ = invoke("GET", "/api/v1/engineers", token=engineer_user["token"])

        assert status == 403

    def test_employee_cannot_list_engineers(self, invoke, registered_user):
        status, _ = invoke("GET", "/api/v1/engineers", token=registered_user["token"])

        assert status == 403
