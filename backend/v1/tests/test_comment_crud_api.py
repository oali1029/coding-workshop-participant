"""Tests for editing and deleting ticket notes.

The rule under test is authorship, and it has no role exemption: an admin reads
everything and may add their own note, but may not rewrite or remove somebody
else's words. Most tests here are a refusal plus a check that the note is
genuinely unchanged afterwards — a 403 that edited anyway would otherwise pass.
"""

from conftest import incident_payload

from app import db


def _report(invoke, token, **overrides):
    _, body = invoke("POST", "/api/v1/incidents", incident_payload(**overrides), token=token)
    return body["incident"]["id"]


def _comment(invoke, incident_id, token, body="Original wording"):
    _, payload = invoke("POST", f"/api/v1/incidents/{incident_id}/comments",
                        {"body": body}, token=token)
    return payload["comment"]["id"]


def _edit(invoke, incident_id, comment_id, token, body="Corrected wording"):
    return invoke("PATCH", f"/api/v1/incidents/{incident_id}/comments/{comment_id}",
                  {"body": body}, token=token)


def _remove(invoke, incident_id, comment_id, token):
    return invoke("DELETE", f"/api/v1/incidents/{incident_id}/comments/{comment_id}",
                  token=token)


def _bodies(invoke, incident_id, token):
    _, body = invoke("GET", f"/api/v1/incidents/{incident_id}/comments", token=token)
    return [c["body"] for c in body["comments"]]


def _stored(comment_id):
    return db.query_one(
        "SELECT body, author_id, incident_id, created_at, edited_at "
        "FROM incident_comments WHERE id = %s",
        (comment_id,),
    )


def _assign(invoke, admin_token, incident_id, assignee_id):
    return invoke("PATCH", f"/api/v1/incidents/{incident_id}",
                  {"assignee_id": assignee_id}, token=admin_token)


class TestAuthorCanEdit:
    def test_employee_edits_own_note(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])
        cid = _comment(invoke, iid, registered_user["token"])

        status, body = _edit(invoke, iid, cid, registered_user["token"], "Actually the left one.")

        assert status == 200
        assert body["comment"]["body"] == "Actually the left one."
        assert _bodies(invoke, iid, registered_user["token"]) == ["Actually the left one."]

    def test_edit_marks_edited_at(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])
        cid = _comment(invoke, iid, registered_user["token"])
        assert _stored(cid)["edited_at"] is None

        _edit(invoke, iid, cid, registered_user["token"])

        assert _stored(cid)["edited_at"] is not None

    def test_edit_preserves_author_incident_and_created_at(self, invoke, registered_user):
        """An edit changes wording, never whose note it is or where it lives."""
        iid = _report(invoke, registered_user["token"])
        cid = _comment(invoke, iid, registered_user["token"])
        before = _stored(cid)

        _edit(invoke, iid, cid, registered_user["token"])

        after = _stored(cid)
        assert after["author_id"] == before["author_id"]
        assert after["incident_id"] == before["incident_id"]
        assert after["created_at"] == before["created_at"]

    def test_engineer_edits_own_note(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        cid = _comment(invoke, iid, engineer_user["token"])

        assert _edit(invoke, iid, cid, engineer_user["token"])[0] == 200

    def test_admin_edits_own_note(self, invoke, registered_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        cid = _comment(invoke, iid, admin_token)

        assert _edit(invoke, iid, cid, admin_token)[0] == 200

    def test_blank_edit_rejected(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])
        cid = _comment(invoke, iid, registered_user["token"])

        status, body = _edit(invoke, iid, cid, registered_user["token"], "   ")

        assert status == 400
        assert body["details"]["field"] == "body"
        assert _stored(cid)["body"] == "Original wording"

    def test_over_length_edit_rejected(self, invoke, registered_user):
        from app.domains.comments import MAX_BODY_LENGTH

        iid = _report(invoke, registered_user["token"])
        cid = _comment(invoke, iid, registered_user["token"])

        assert _edit(invoke, iid, cid, registered_user["token"],
                     "x" * (MAX_BODY_LENGTH + 1))[0] == 400


class TestAuthorCanDelete:
    def test_employee_deletes_own_note(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])
        cid = _comment(invoke, iid, registered_user["token"])

        status, body = _remove(invoke, iid, cid, registered_user["token"])

        assert status == 200
        assert body["deleted"] == cid
        assert _bodies(invoke, iid, registered_user["token"]) == []
        assert _stored(cid) is None

    def test_only_that_note_goes(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])
        first = _comment(invoke, iid, registered_user["token"], "one")
        _comment(invoke, iid, registered_user["token"], "two")

        _remove(invoke, iid, first, registered_user["token"])

        assert _bodies(invoke, iid, registered_user["token"]) == ["two"]

    def test_engineer_deletes_own_note(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        cid = _comment(invoke, iid, engineer_user["token"])

        assert _remove(invoke, iid, cid, engineer_user["token"])[0] == 200

    def test_deleting_twice_is_not_found(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])
        cid = _comment(invoke, iid, registered_user["token"])

        assert _remove(invoke, iid, cid, registered_user["token"])[0] == 200
        assert _remove(invoke, iid, cid, registered_user["token"])[0] == 404

    def test_incident_survives_its_note_being_deleted(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])
        cid = _comment(invoke, iid, registered_user["token"])

        _remove(invoke, iid, cid, registered_user["token"])

        assert invoke("GET", f"/api/v1/incidents/{iid}",
                      token=registered_user["token"])[0] == 200


class TestNobodyElseMayChangeANote:
    def test_another_employee_refused(self, invoke, registered_user, second_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        cid = _comment(invoke, iid, registered_user["token"])

        # The second employee cannot even see this incident, so it is a 404.
        assert _edit(invoke, iid, cid, second_user["token"])[0] == 404
        assert _remove(invoke, iid, cid, second_user["token"])[0] == 404
        assert _stored(cid)["body"] == "Original wording"

    def test_engineer_cannot_change_the_reporters_note(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """The engineer can see this note; they still may not rewrite it."""
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        cid = _comment(invoke, iid, registered_user["token"])

        assert _edit(invoke, iid, cid, engineer_user["token"])[0] == 403
        assert _remove(invoke, iid, cid, engineer_user["token"])[0] == 403
        assert _stored(cid)["body"] == "Original wording"

    def test_admin_cannot_rewrite_another_persons_note(
        self, invoke, registered_user, admin_token
    ):
        """Deliberate: an admin who could silently edit notes would make the
        whole record untrustworthy. They can delete the incident instead."""
        iid = _report(invoke, registered_user["token"])
        cid = _comment(invoke, iid, registered_user["token"])

        status, _ = _edit(invoke, iid, cid, admin_token, "Never said this")

        assert status == 403
        assert _stored(cid)["body"] == "Original wording"

    def test_admin_cannot_delete_another_persons_note(
        self, invoke, registered_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        cid = _comment(invoke, iid, registered_user["token"])

        assert _remove(invoke, iid, cid, admin_token)[0] == 403
        assert _stored(cid) is not None

    def test_engineer_who_loses_the_assignment_loses_access(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        cid = _comment(invoke, iid, engineer_user["token"])

        invoke("PATCH", f"/api/v1/incidents/{iid}", {"assignee_id": None}, token=admin_token)

        # Their own note, but the incident is no longer theirs to see.
        assert _edit(invoke, iid, cid, engineer_user["token"])[0] == 404

    def test_requires_authentication(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])
        cid = _comment(invoke, iid, registered_user["token"])

        assert invoke("PATCH", f"/api/v1/incidents/{iid}/comments/{cid}",
                      {"body": "x"})[0] == 401
        assert invoke("DELETE", f"/api/v1/incidents/{iid}/comments/{cid}")[0] == 401


class TestWrongIdentifiers:
    def test_unknown_comment(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])

        assert _edit(invoke, iid, 999999, registered_user["token"])[0] == 404
        assert _remove(invoke, iid, 999999, registered_user["token"])[0] == 404

    def test_non_numeric_comment_id(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])

        assert invoke("PATCH", f"/api/v1/incidents/{iid}/comments/abc",
                      {"body": "x"}, token=registered_user["token"])[0] == 404

    def test_comment_from_another_incident(self, invoke, registered_user):
        """The comment id must belong to the incident in the path."""
        first = _report(invoke, registered_user["token"])
        second = _report(invoke, registered_user["token"])
        cid = _comment(invoke, first, registered_user["token"])

        assert _edit(invoke, second, cid, registered_user["token"])[0] == 404
        assert _stored(cid)["body"] == "Original wording"


class TestClosedIncidentsSealTheRecord:
    def test_edit_refused_when_closed(self, invoke, registered_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        cid = _comment(invoke, iid, registered_user["token"])
        invoke("PATCH", f"/api/v1/incidents/{iid}", {"status": "CLOSED"}, token=admin_token)

        status, _ = _edit(invoke, iid, cid, registered_user["token"])

        assert status == 403
        assert _stored(cid)["body"] == "Original wording"

    def test_delete_refused_when_closed(self, invoke, registered_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        cid = _comment(invoke, iid, registered_user["token"])
        invoke("PATCH", f"/api/v1/incidents/{iid}", {"status": "CLOSED"}, token=admin_token)

        assert _remove(invoke, iid, cid, registered_user["token"])[0] == 403
        assert _stored(cid) is not None

    def test_still_readable_when_closed(self, invoke, registered_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        _comment(invoke, iid, registered_user["token"], "said before closing")
        invoke("PATCH", f"/api/v1/incidents/{iid}", {"status": "CLOSED"}, token=admin_token)

        assert _bodies(invoke, iid, registered_user["token"]) == ["said before closing"]

    def test_reopening_allows_editing_again(self, invoke, registered_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        cid = _comment(invoke, iid, registered_user["token"])
        invoke("PATCH", f"/api/v1/incidents/{iid}", {"status": "CLOSED"}, token=admin_token)
        assert _edit(invoke, iid, cid, registered_user["token"])[0] == 403

        invoke("PATCH", f"/api/v1/incidents/{iid}", {"status": "OPEN"}, token=admin_token)

        assert _edit(invoke, iid, cid, registered_user["token"])[0] == 200


class TestIncidentDeletionStillCascades:
    def test_deleting_an_incident_removes_its_notes(
        self, invoke, registered_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        first = _comment(invoke, iid, registered_user["token"], "one")
        second = _comment(invoke, iid, admin_token, "two")

        status, body = invoke("DELETE", f"/api/v1/incidents/{iid}", token=admin_token)

        assert status == 200
        assert body["comments_deleted"] == 2
        assert _stored(first) is None
        assert _stored(second) is None
