"""Tests for releasing a demoted engineer's live work.

Demotion has two effects that must not come apart: the role changes, and every
incident of theirs that is not CLOSED loses its assignee. A former engineer left
holding live tickets would sit in a queue they can no longer open and would keep
counting towards the workload an admin assigns from.

CLOSED is the deliberate exception — that is a record of who did the work.
"""

import pytest
from conftest import incident_payload

from app import db
from app.domains import users


def _report(invoke, token, **overrides):
    _, body = invoke("POST", "/api/v1/incidents", incident_payload(**overrides), token=token)
    return body["incident"]["id"]


def _assign(invoke, admin_token, incident_id, assignee_id):
    return invoke("PATCH", f"/api/v1/incidents/{incident_id}",
                  {"assignee_id": assignee_id}, token=admin_token)


def _demote(invoke, admin_token, user_id):
    return invoke("PATCH", f"/api/v1/users/{user_id}/role",
                  {"role": "EMPLOYEE"}, token=admin_token)


def _promote(invoke, admin_token, user_id):
    return invoke("PATCH", f"/api/v1/users/{user_id}/role",
                  {"role": "ENGINEER"}, token=admin_token)


def _row(incident_id):
    return db.query_one(
        "SELECT status, assignee_id, assigned_at FROM incidents WHERE id = %s",
        (incident_id,),
    )


def _at_status(invoke, admin_token, engineer_user, registered_user, status):
    """An incident assigned to the engineer and moved to `status`."""
    iid = _report(invoke, registered_user["token"])
    _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

    if status != "OPEN":
        changes = {"status": status}
        if status == "BLOCKED":
            changes["blocked_reason"] = "Waiting on a part."
        invoke("PATCH", f"/api/v1/incidents/{iid}", changes, token=admin_token)

    return iid


class TestActiveWorkIsReleased:
    @pytest.mark.parametrize("status", ["OPEN", "IN_PROGRESS", "BLOCKED", "RESOLVED"])
    def test_active_incident_becomes_unassigned(
        self, invoke, registered_user, engineer_user, admin_token, status
    ):
        iid = _at_status(invoke, admin_token, engineer_user, registered_user, status)
        assert _row(iid)["assignee_id"] == engineer_user["user"]["id"]

        _demote(invoke, admin_token, engineer_user["user"]["id"])

        after = _row(iid)
        assert after["assignee_id"] is None
        # The whole point: releasing the work must not also move the ticket.
        assert after["status"] == status

    def test_closed_incident_keeps_its_engineer(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """History: this person really did do the work."""
        iid = _at_status(invoke, admin_token, engineer_user, registered_user, "CLOSED")

        _demote(invoke, admin_token, engineer_user["user"]["id"])

        after = _row(iid)
        assert after["assignee_id"] == engineer_user["user"]["id"]
        assert after["status"] == "CLOSED"

    def test_every_status_at_once(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """The worked example: four released, the closed one kept."""
        incidents = {
            status: _at_status(invoke, admin_token, engineer_user, registered_user, status)
            for status in ("OPEN", "IN_PROGRESS", "BLOCKED", "RESOLVED", "CLOSED")
        }

        status_code, body = _demote(invoke, admin_token, engineer_user["user"]["id"])

        assert status_code == 200
        assert body["incidents_unassigned"] == 4

        for status, iid in incidents.items():
            row = _row(iid)
            assert row["status"] == status, f"{status} must not change"
            if status == "CLOSED":
                assert row["assignee_id"] == engineer_user["user"]["id"]
            else:
                assert row["assignee_id"] is None, f"{status} should be unassigned"

    def test_multiple_active_tickets_all_released(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        ids = []
        for _ in range(4):
            iid = _report(invoke, registered_user["token"])
            _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
            ids.append(iid)

        _, body = _demote(invoke, admin_token, engineer_user["user"]["id"])

        assert body["incidents_unassigned"] == 4
        assert all(_row(iid)["assignee_id"] is None for iid in ids)

    def test_assigned_at_is_kept(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """It was assigned once; that remains true and the timing report needs it."""
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        before = _row(iid)["assigned_at"]

        _demote(invoke, admin_token, engineer_user["user"]["id"])

        assert _row(iid)["assigned_at"] == before


class TestScope:
    def test_other_engineers_are_untouched(
        self, invoke, registered_user, engineer_user, second_engineer, admin_token
    ):
        mine = _report(invoke, registered_user["token"])
        theirs = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, mine, engineer_user["user"]["id"])
        _assign(invoke, admin_token, theirs, second_engineer["user"]["id"])

        _demote(invoke, admin_token, engineer_user["user"]["id"])

        assert _row(mine)["assignee_id"] is None
        assert _row(theirs)["assignee_id"] == second_engineer["user"]["id"]

    def test_unassigned_incidents_are_not_counted(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        _report(invoke, registered_user["token"])
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        _, body = _demote(invoke, admin_token, engineer_user["user"]["id"])

        assert body["incidents_unassigned"] == 1

    def test_role_becomes_employee(self, invoke, engineer_user, admin_token):
        status, body = _demote(invoke, admin_token, engineer_user["user"]["id"])

        assert status == 200
        assert body["user"]["role"] == "EMPLOYEE"
        assert db.query_one(
            "SELECT role FROM users WHERE id = %s", (engineer_user["user"]["id"],)
        )["role"] == "EMPLOYEE"

    def test_promotion_releases_nothing(self, invoke, registered_user, admin_token):
        """Only demotion sheds work; promoting an employee has none to shed."""
        _report(invoke, registered_user["token"])

        _, body = _promote(invoke, admin_token, registered_user["user"]["id"])

        assert body["incidents_unassigned"] == 0

    def test_engineer_to_engineer_releases_nothing(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """Re-sending the same role is not a demotion and must not shed work."""
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        _, body = _promote(invoke, admin_token, engineer_user["user"]["id"])

        assert body["incidents_unassigned"] == 0
        assert _row(iid)["assignee_id"] == engineer_user["user"]["id"]

    def test_employee_cannot_demote(self, invoke, registered_user, engineer_user):
        assert invoke("PATCH", f"/api/v1/users/{engineer_user['user']['id']}/role",
                      {"role": "EMPLOYEE"}, token=registered_user["token"])[0] == 403

    def test_engineer_cannot_demote_a_peer(
        self, invoke, engineer_user, second_engineer
    ):
        assert invoke("PATCH", f"/api/v1/users/{second_engineer['user']['id']}/role",
                      {"role": "EMPLOYEE"}, token=engineer_user["token"])[0] == 403


class TestVisibleEverywhereAfterwards:
    def test_shows_as_unassigned_in_admin_filter(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"], title="Released ticket")
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        _demote(invoke, admin_token, engineer_user["user"]["id"])

        _, body = invoke("GET", "/api/v1/admin/incidents", token=admin_token,
                         query={"q": "Released ticket", "assignee": "unassigned"})
        assert [row["id"] for row in body["incidents"]] == [iid]

    def test_drops_out_of_the_engineer_queue(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        _demote(invoke, admin_token, engineer_user["user"]["id"])
        # They are an employee now, so the engineers-only queue refuses them.
        assert invoke("GET", "/api/v1/incidents/assigned",
                      token=engineer_user["token"])[0] == 403

    def test_workload_reporting_drops_them(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        _demote(invoke, admin_token, engineer_user["user"]["id"])

        _, summary = invoke("GET", "/api/v1/admin/analytics", token=admin_token)
        # No longer an engineer, so absent from the roster entirely.
        assert engineer_user["user"]["id"] not in [e["id"] for e in summary["engineers"]]
        assert _row(iid)["assignee_id"] is None


class TestAtomicity:
    def test_a_failed_unassignment_rolls_back_the_role_change(
        self, invoke, registered_user, engineer_user, admin_token, monkeypatch
    ):
        """The state this change exists to prevent must be unreachable.

        The unassignment SQL is replaced with a statement PostgreSQL will
        reject, standing in for any database failure between the two writes.
        Both happen in one transaction, so the role change must roll back with
        it rather than leaving an ex-engineer holding live work.
        """
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        monkeypatch.setattr(
            users, "_UNASSIGN_ACTIVE_SQL", "UPDATE incidents SET no_such_column = %s WHERE id = %s"
        )

        status, _ = _demote(invoke, admin_token, engineer_user["user"]["id"])

        assert status == 500, "the failure must surface, not be swallowed"
        assert db.query_one(
            "SELECT role FROM users WHERE id = %s", (engineer_user["user"]["id"],)
        )["role"] == "ENGINEER", "role change must have rolled back"
        assert _row(iid)["assignee_id"] == engineer_user["user"]["id"]

    def test_the_connection_still_works_afterwards(
        self, invoke, registered_user, engineer_user, admin_token, monkeypatch
    ):
        """A rolled-back transaction must not poison the pooled connection."""
        monkeypatch.setattr(
            users, "_UNASSIGN_ACTIVE_SQL", "UPDATE incidents SET no_such_column = %s WHERE id = %s"
        )
        _demote(invoke, admin_token, engineer_user["user"]["id"])
        monkeypatch.undo()

        # A perfectly ordinary request, which would fail on a broken connection.
        assert invoke("GET", "/api/v1/incidents", token=registered_user["token"])[0] == 200

    def test_succeeds_normally_once_the_failure_is_removed(
        self, invoke, registered_user, engineer_user, admin_token, monkeypatch
    ):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        monkeypatch.setattr(
            users, "_UNASSIGN_ACTIVE_SQL", "UPDATE incidents SET no_such_column = %s WHERE id = %s"
        )
        _demote(invoke, admin_token, engineer_user["user"]["id"])
        monkeypatch.undo()

        status, body = _demote(invoke, admin_token, engineer_user["user"]["id"])

        assert status == 200
        assert body["incidents_unassigned"] == 1
        assert _row(iid)["assignee_id"] is None
