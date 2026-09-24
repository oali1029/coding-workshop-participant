"""Tests for priority management, escalation requests and blocked reasons.

The design being tested: priority is the admin's call, escalation is how an
employee asks for it, and BLOCKED always says why. Most of these tests are about
who may do which half.
"""

from conftest import incident_payload


def _report(invoke, token, **overrides):
    _, body = invoke("POST", "/api/v1/incidents", incident_payload(**overrides), token=token)
    return body["incident"]["id"]


def _patch(invoke, incident_id, changes, token):
    return invoke("PATCH", f"/api/v1/incidents/{incident_id}", changes, token=token)


def _assign(invoke, admin_token, incident_id, assignee_id):
    return _patch(invoke, incident_id, {"assignee_id": assignee_id}, admin_token)


def _escalate(invoke, incident_id, token, reason="The whole floor is affected."):
    return invoke("POST", f"/api/v1/incidents/{incident_id}/escalation",
                  {"reason": reason}, token=token)


def _get(invoke, incident_id, token):
    _, body = invoke("GET", f"/api/v1/incidents/{incident_id}", token=token)
    return body["incident"]


class TestPriorityAtCreation:
    def test_reporter_chooses_priority(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"], priority="HIGH")

        assert _get(invoke, iid, registered_user["token"])["priority"] == "HIGH"

    def test_defaults_to_medium(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])

        assert _get(invoke, iid, registered_user["token"])["priority"] == "MEDIUM"


class TestPriorityChanges:
    def test_admin_can_change_priority(self, invoke, registered_user, admin_token):
        iid = _report(invoke, registered_user["token"], priority="LOW")

        status, body = _patch(invoke, iid, {"priority": "HIGH"}, admin_token)

        assert status == 200
        assert body["incident"]["priority"] == "HIGH"

    def test_admin_can_change_priority_alone(self, invoke, registered_user, admin_token):
        """Priority is a complete change on its own; no status needs to come with it."""
        iid = _report(invoke, registered_user["token"])

        assert _patch(invoke, iid, {"priority": "LOW"}, admin_token)[0] == 200

    def test_engineer_cannot_change_priority(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """The engineer does the work; re-ranking it is not theirs to do."""
        iid = _report(invoke, registered_user["token"], priority="LOW")
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        status, _ = _patch(invoke, iid, {"priority": "HIGH"}, engineer_user["token"])

        assert status == 403
        assert _get(invoke, iid, admin_token)["priority"] == "LOW"

    def test_engineer_priority_change_blocks_the_whole_request(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """A refused call must change nothing, not apply the allowed half."""
        iid = _report(invoke, registered_user["token"], priority="LOW")
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        _patch(invoke, iid, {"status": "IN_PROGRESS", "priority": "HIGH"},
               engineer_user["token"])

        after = _get(invoke, iid, admin_token)
        assert after["priority"] == "LOW"
        assert after["status"] == "OPEN"

    def test_employee_cannot_change_priority(self, invoke, registered_user):
        """Not even on their own incident — PATCH is closed to employees."""
        iid = _report(invoke, registered_user["token"], priority="LOW")

        assert _patch(invoke, iid, {"priority": "HIGH"}, registered_user["token"])[0] == 403

    def test_employee_cannot_change_another_incidents_priority(
        self, invoke, registered_user, second_user
    ):
        iid = _report(invoke, registered_user["token"])

        assert _patch(invoke, iid, {"priority": "HIGH"}, second_user["token"])[0] == 403

    def test_invalid_priority_rejected(self, invoke, registered_user, admin_token):
        iid = _report(invoke, registered_user["token"])

        status, body = _patch(invoke, iid, {"priority": "URGENT"}, admin_token)

        assert status == 400
        assert body["details"]["field"] == "priority"


class TestEscalationRequest:
    def test_reporter_can_request(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])

        status, body = _escalate(invoke, iid, registered_user["token"],
                                 "This is blocking our whole team.")

        assert status == 200
        assert body["incident"]["escalation_requested"] is True
        assert body["incident"]["escalation_reason"] == "This is blocking our whole team."
        assert body["incident"]["escalated_at"] is not None

    def test_reason_persists_and_is_readable_by_admin(
        self, invoke, registered_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _escalate(invoke, iid, registered_user["token"], "Nobody can reach the third floor.")

        seen = _get(invoke, iid, admin_token)

        assert seen["escalation_requested"] is True
        assert seen["escalation_reason"] == "Nobody can reach the third floor."

    def test_reason_is_required(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])

        status, body = _escalate(invoke, iid, registered_user["token"], "   ")

        assert status == 400
        assert body["details"]["field"] == "reason"

    def test_escalation_does_not_change_priority(self, invoke, registered_user, admin_token):
        """Asking is not the same as deciding — the admin still sets priority."""
        iid = _report(invoke, registered_user["token"], priority="LOW")
        _escalate(invoke, iid, registered_user["token"])

        assert _get(invoke, iid, admin_token)["priority"] == "LOW"

    def test_another_employee_cannot_escalate(self, invoke, registered_user, second_user):
        iid = _report(invoke, registered_user["token"])

        assert _escalate(invoke, iid, second_user["token"])[0] == 404

    def test_assigned_engineer_cannot_escalate(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """Escalation is the reporter's voice, not the assignee's."""
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        assert _escalate(invoke, iid, engineer_user["token"])[0] == 404

    def test_admin_cannot_escalate_someone_elses_report(
        self, invoke, registered_user, admin_token
    ):
        """An admin sets the priority directly instead."""
        iid = _report(invoke, registered_user["token"])

        assert _escalate(invoke, iid, admin_token)[0] == 404

    def test_allowed_from_open_in_progress_and_blocked(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        for value in ("OPEN", "IN_PROGRESS", "BLOCKED"):
            iid = _report(invoke, registered_user["token"])
            _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
            if value != "OPEN":
                _patch(invoke, iid, {"status": value, "blocked_reason": "Part on order."},
                       admin_token)

            assert _escalate(invoke, iid, registered_user["token"])[0] == 200, value

    def test_refused_once_resolved(self, invoke, registered_user, engineer_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        _patch(invoke, iid, {"status": "RESOLVED"}, engineer_user["token"])

        assert _escalate(invoke, iid, registered_user["token"])[0] == 403

    def test_refused_once_closed(self, invoke, registered_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        _patch(invoke, iid, {"status": "CLOSED"}, admin_token)

        assert _escalate(invoke, iid, registered_user["token"])[0] == 403

    def test_unknown_incident(self, invoke, registered_user):
        assert _escalate(invoke, 999999, registered_user["token"])[0] == 404

    def test_requires_authentication(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])

        assert invoke("POST", f"/api/v1/incidents/{iid}/escalation",
                      {"reason": "x"})[0] == 401


class TestEscalationAcknowledgement:
    def test_admin_clears_the_flag_but_keeps_the_reason(
        self, invoke, registered_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _escalate(invoke, iid, registered_user["token"], "Blocking the whole floor.")

        status, body = invoke("DELETE", f"/api/v1/incidents/{iid}/escalation",
                              token=admin_token)

        assert status == 200
        assert body["incident"]["escalation_requested"] is False
        # The record still says what was asked for and when.
        assert body["incident"]["escalation_reason"] == "Blocking the whole floor."
        assert body["incident"]["escalated_at"] is not None

    def test_employee_cannot_acknowledge_their_own_request(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])
        _escalate(invoke, iid, registered_user["token"])

        assert invoke("DELETE", f"/api/v1/incidents/{iid}/escalation",
                      token=registered_user["token"])[0] == 403

    def test_engineer_cannot_acknowledge(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        _escalate(invoke, iid, registered_user["token"])

        assert invoke("DELETE", f"/api/v1/incidents/{iid}/escalation",
                      token=engineer_user["token"])[0] == 403

    def test_can_be_requested_again_afterwards(self, invoke, registered_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        _escalate(invoke, iid, registered_user["token"], "First ask.")
        invoke("DELETE", f"/api/v1/incidents/{iid}/escalation", token=admin_token)

        _, body = _escalate(invoke, iid, registered_user["token"], "Still not fixed.")

        assert body["incident"]["escalation_requested"] is True
        assert body["incident"]["escalation_reason"] == "Still not fixed."

    def test_unknown_incident(self, invoke, admin_token):
        assert invoke("DELETE", "/api/v1/incidents/999999/escalation",
                      token=admin_token)[0] == 404

    def test_counted_in_admin_analytics(self, invoke, registered_user, admin_token):
        _, before = invoke("GET", "/api/v1/admin/analytics", token=admin_token)
        iid = _report(invoke, registered_user["token"])
        _escalate(invoke, iid, registered_user["token"])

        _, after = invoke("GET", "/api/v1/admin/analytics", token=admin_token)
        assert after["escalations_open"] == before["escalations_open"] + 1

        invoke("DELETE", f"/api/v1/incidents/{iid}/escalation", token=admin_token)

        _, cleared = invoke("GET", "/api/v1/admin/analytics", token=admin_token)
        assert cleared["escalations_open"] == before["escalations_open"]


class TestBlockedReason:
    def test_required_when_blocking(self, invoke, registered_user, engineer_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        status, body = _patch(invoke, iid, {"status": "BLOCKED"}, engineer_user["token"])

        assert status == 400
        assert body["details"]["field"] == "blocked_reason"

    def test_blank_reason_rejected(self, invoke, registered_user, engineer_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        status, _ = _patch(invoke, iid, {"status": "BLOCKED", "blocked_reason": "   "},
                           engineer_user["token"])

        assert status == 400

    def test_reason_persists(self, invoke, registered_user, engineer_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        _, body = _patch(invoke, iid,
                         {"status": "BLOCKED", "blocked_reason": "Waiting on a replacement pump."},
                         engineer_user["token"])

        assert body["incident"]["blocked_reason"] == "Waiting on a replacement pump."
        assert _get(invoke, iid, registered_user["token"])["blocked_reason"] == (
            "Waiting on a replacement pump."
        )

    def test_status_is_unchanged_when_the_reason_is_missing(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        _patch(invoke, iid, {"status": "BLOCKED"}, engineer_user["token"])

        assert _get(invoke, iid, admin_token)["status"] == "OPEN"

    def test_cleared_when_unblocked(self, invoke, registered_user, engineer_user, admin_token):
        """A stale reason must never show against a ticket that is moving again."""
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        _patch(invoke, iid, {"status": "BLOCKED", "blocked_reason": "Part on order."},
               engineer_user["token"])

        _patch(invoke, iid, {"status": "IN_PROGRESS"}, engineer_user["token"])

        assert _get(invoke, iid, admin_token)["blocked_reason"] is None

    def test_admin_can_block_with_a_reason(self, invoke, registered_user, admin_token):
        iid = _report(invoke, registered_user["token"])

        _, body = _patch(invoke, iid,
                         {"status": "BLOCKED", "blocked_reason": "Access denied by security."},
                         admin_token)

        assert body["incident"]["blocked_reason"] == "Access denied by security."
