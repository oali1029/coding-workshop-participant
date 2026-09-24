"""Tests for incident comments.

Who may read and write is the same rule as who may see the incident, so the
refusals are the important cases: an unrelated employee and an unassigned
engineer must both be shut out.
"""

from conftest import incident_payload

from app import db


def _report(invoke, token, title="Monitor flickering"):
    _, body = invoke("POST", "/api/v1/incidents", incident_payload(title=title), token=token)
    return body["incident"]["id"]


def _comment(invoke, incident_id, token, body="A comment"):
    return invoke("POST", f"/api/v1/incidents/{incident_id}/comments", {"body": body}, token=token)


def _assign(invoke, admin_token, incident_id, assignee_id):
    return invoke(
        "PATCH", f"/api/v1/incidents/{incident_id}", {"assignee_id": assignee_id},
        token=admin_token,
    )


class TestEmployeeComments:
    def test_can_comment_on_own_incident(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])

        status, body = _comment(invoke, iid, registered_user["token"], "It turns off often.")

        assert status == 201
        assert body["comment"]["body"] == "It turns off often."
        assert body["comment"]["author_name"] == "Test Person"
        assert body["comment"]["author_role"] == "EMPLOYEE"

    def test_can_read_own_incident_comments(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])
        _comment(invoke, iid, registered_user["token"], "First")

        status, body = invoke("GET", f"/api/v1/incidents/{iid}/comments",
                              token=registered_user["token"])

        assert status == 200
        assert [c["body"] for c in body["comments"]] == ["First"]

    def test_cannot_comment_on_another_employees_incident(
        self, invoke, registered_user, second_user
    ):
        iid = _report(invoke, registered_user["token"])

        status, _ = _comment(invoke, iid, second_user["token"], "Not mine")

        assert status == 404

    def test_cannot_read_another_employees_comments(self, invoke, registered_user, second_user):
        iid = _report(invoke, registered_user["token"])
        _comment(invoke, iid, registered_user["token"], "Private")

        status, _ = invoke("GET", f"/api/v1/incidents/{iid}/comments",
                           token=second_user["token"])

        assert status == 404

    def test_requires_authentication(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])

        assert invoke("GET", f"/api/v1/incidents/{iid}/comments")[0] == 401
        assert invoke("POST", f"/api/v1/incidents/{iid}/comments", {"body": "x"})[0] == 401


class TestEngineerComments:
    def test_assigned_engineer_can_comment(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        status, body = _comment(invoke, iid, engineer_user["token"], "Checking the cable.")

        assert status == 201
        assert body["comment"]["author_role"] == "ENGINEER"

    def test_unassigned_engineer_is_refused(self, invoke, registered_user, engineer_user):
        """Being an engineer grants nothing; being the assignee does."""
        iid = _report(invoke, registered_user["token"])

        assert _comment(invoke, iid, engineer_user["token"])[0] == 404
        assert invoke("GET", f"/api/v1/incidents/{iid}/comments",
                      token=engineer_user["token"])[0] == 404

    def test_access_begins_at_assignment(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        assert _comment(invoke, iid, engineer_user["token"])[0] == 404

        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        assert _comment(invoke, iid, engineer_user["token"])[0] == 201


class TestAdminComments:
    def test_admin_can_comment_on_any_incident(self, invoke, registered_user, admin_token):
        iid = _report(invoke, registered_user["token"])

        status, body = _comment(invoke, iid, admin_token, "Reviewing.")

        assert status == 201
        assert body["comment"]["author_role"] == "FACILITY_ADMIN"

    def test_admin_can_read_any_incident_comments(self, invoke, registered_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        _comment(invoke, iid, registered_user["token"], "Mine")

        status, body = invoke("GET", f"/api/v1/incidents/{iid}/comments", token=admin_token)

        assert status == 200
        assert len(body["comments"]) == 1


class TestCommentValidation:
    def test_blank_is_rejected(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])

        status, body = _comment(invoke, iid, registered_user["token"], "")

        assert status == 400
        assert body["details"]["field"] == "body"

    def test_whitespace_only_is_rejected(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])

        assert _comment(invoke, iid, registered_user["token"], "   \n\t  ")[0] == 400

    def test_over_length_is_rejected(self, invoke, registered_user):
        from app.domains.comments import MAX_BODY_LENGTH

        iid = _report(invoke, registered_user["token"])

        status, body = _comment(invoke, iid, registered_user["token"], "x" * (MAX_BODY_LENGTH + 1))

        assert status == 400
        assert body["details"]["field"] == "body"

    def test_body_is_trimmed(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])

        _, body = _comment(invoke, iid, registered_user["token"], "  padded  ")

        assert body["comment"]["body"] == "padded"

    def test_unknown_incident_is_not_found(self, invoke, registered_user):
        assert _comment(invoke, 999999, registered_user["token"])[0] == 404

    def test_non_numeric_incident_id(self, invoke, registered_user):
        status, _ = invoke("GET", "/api/v1/incidents/abc/comments",
                           token=registered_user["token"])
        assert status == 404


class TestCommentOrderingAndLifecycle:
    def test_oldest_first(self, invoke, registered_user, engineer_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        _comment(invoke, iid, registered_user["token"], "one")
        _comment(invoke, iid, engineer_user["token"], "two")
        _comment(invoke, iid, admin_token, "three")

        _, body = invoke("GET", f"/api/v1/incidents/{iid}/comments", token=admin_token)

        assert [c["body"] for c in body["comments"]] == ["one", "two", "three"]

    def test_empty_when_none(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])

        _, body = invoke("GET", f"/api/v1/incidents/{iid}/comments",
                         token=registered_user["token"])

        assert body["comments"] == []

    def test_survive_status_changes(self, invoke, registered_user, engineer_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        _comment(invoke, iid, registered_user["token"], "before")

        for value in ("IN_PROGRESS", "BLOCKED", "RESOLVED"):
            invoke("PATCH", f"/api/v1/incidents/{iid}", {"status": value},
                   token=engineer_user["token"])

        _, body = invoke("GET", f"/api/v1/incidents/{iid}/comments", token=admin_token)

        assert [c["body"] for c in body["comments"]] == ["before"]

    def test_closed_incident_keeps_comments_readable(
        self, invoke, registered_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _comment(invoke, iid, registered_user["token"], "said before closing")
        invoke("PATCH", f"/api/v1/incidents/{iid}", {"status": "CLOSED"}, token=admin_token)

        status, body = invoke("GET", f"/api/v1/incidents/{iid}/comments",
                              token=registered_user["token"])

        assert status == 200
        assert [c["body"] for c in body["comments"]] == ["said before closing"]

    def test_closed_incident_rejects_new_comments(self, invoke, registered_user, admin_token):
        """CLOSED is the admin's acceptance that the work is finished."""
        iid = _report(invoke, registered_user["token"])
        invoke("PATCH", f"/api/v1/incidents/{iid}", {"status": "CLOSED"}, token=admin_token)

        status, body = _comment(invoke, iid, registered_user["token"], "one more thing")

        assert status == 403
        assert body["error"] == "forbidden"

    def test_closed_rejects_admin_comments_too(self, invoke, registered_user, admin_token):
        """The rule is about the ticket's state, not the caller's role."""
        iid = _report(invoke, registered_user["token"])
        invoke("PATCH", f"/api/v1/incidents/{iid}", {"status": "CLOSED"}, token=admin_token)

        assert _comment(invoke, iid, admin_token)[0] == 403

    def test_reopening_allows_comments_again(self, invoke, registered_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        invoke("PATCH", f"/api/v1/incidents/{iid}", {"status": "CLOSED"}, token=admin_token)
        assert _comment(invoke, iid, registered_user["token"])[0] == 403

        invoke("PATCH", f"/api/v1/incidents/{iid}", {"status": "OPEN"}, token=admin_token)

        assert _comment(invoke, iid, registered_user["token"])[0] == 201

    def test_comments_are_removed_with_their_incident(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])
        _comment(invoke, iid, registered_user["token"], "goes away")

        db.execute("DELETE FROM incidents WHERE id = %s", (iid,))

        row = db.query_one(
            "SELECT COUNT(*) AS n FROM incident_comments WHERE incident_id = %s", (iid,)
        )
        assert row["n"] == 0
