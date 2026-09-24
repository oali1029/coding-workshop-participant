"""Tests for permanent incident deletion.

Two things matter here beyond the happy path: that only an admin can do it, and
that the blast radius is exactly one incident plus its comments. Several tests
below exist purely to prove what deletion does *not* remove.
"""

import uuid

from conftest import TEST_BUILDING_PREFIX, incident_payload

from app import db


def _report(invoke, token, **overrides):
    _, body = invoke("POST", "/api/v1/incidents", incident_payload(**overrides), token=token)
    return body["incident"]["id"]


def _comment(invoke, incident_id, token, body="A comment"):
    return invoke("POST", f"/api/v1/incidents/{incident_id}/comments", {"body": body}, token=token)


def _assign(invoke, admin_token, incident_id, assignee_id):
    return invoke("PATCH", f"/api/v1/incidents/{incident_id}",
                  {"assignee_id": assignee_id}, token=admin_token)


def _delete(invoke, incident_id, token):
    return invoke("DELETE", f"/api/v1/incidents/{incident_id}", token=token)


def _exists(table, row_id):
    return db.query_one(f"SELECT id FROM {table} WHERE id = %s", (row_id,)) is not None


class TestDeleteAuthorization:
    def test_employee_refused(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])

        status, _ = _delete(invoke, iid, registered_user["token"])

        assert status == 403
        assert _exists("incidents", iid), "the incident must survive a refused delete"

    def test_reporter_cannot_delete_own_incident(self, invoke, registered_user):
        """Owning a report does not mean owning the record."""
        iid = _report(invoke, registered_user["token"])

        assert _delete(invoke, iid, registered_user["token"])[0] == 403
        assert _exists("incidents", iid)

    def test_engineer_refused(self, invoke, registered_user, engineer_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        status, _ = _delete(invoke, iid, engineer_user["token"])

        assert status == 403
        assert _exists("incidents", iid), "even the assigned engineer must not delete it"

    def test_anonymous_refused(self, invoke, registered_user):
        iid = _report(invoke, registered_user["token"])

        assert _delete(invoke, iid, None)[0] == 401
        assert _exists("incidents", iid)


class TestDeleteSucceeds:
    def test_admin_deletes_open_incident(self, invoke, registered_user, admin_token):
        iid = _report(invoke, registered_user["token"])

        status, body = _delete(invoke, iid, admin_token)

        assert status == 200
        assert body["deleted"] == iid
        assert not _exists("incidents", iid)

    def test_admin_deletes_closed_incident(self, invoke, registered_user, admin_token):
        """Closing records finished work; deleting removes the record. Both allowed."""
        iid = _report(invoke, registered_user["token"])
        invoke("PATCH", f"/api/v1/incidents/{iid}", {"status": "CLOSED"}, token=admin_token)

        assert _delete(invoke, iid, admin_token)[0] == 200
        assert not _exists("incidents", iid)

    def test_deletable_from_every_status(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        for value in ("OPEN", "IN_PROGRESS", "BLOCKED", "RESOLVED", "CLOSED"):
            iid = _report(invoke, registered_user["token"])
            _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
            if value != "OPEN":
                invoke("PATCH", f"/api/v1/incidents/{iid}", {"status": value}, token=admin_token)

            assert _delete(invoke, iid, admin_token)[0] == 200, f"failed from {value}"
            assert not _exists("incidents", iid)

    def test_unknown_incident(self, invoke, admin_token):
        assert _delete(invoke, 999999, admin_token)[0] == 404

    def test_non_numeric_id(self, invoke, admin_token):
        assert invoke("DELETE", "/api/v1/incidents/abc", token=admin_token)[0] == 404

    def test_deleting_twice_is_not_found(self, invoke, registered_user, admin_token):
        iid = _report(invoke, registered_user["token"])

        assert _delete(invoke, iid, admin_token)[0] == 200
        assert _delete(invoke, iid, admin_token)[0] == 404


class TestDeletedIncidentIsGone:
    def test_get_returns_404(self, invoke, registered_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        _delete(invoke, iid, admin_token)

        assert invoke("GET", f"/api/v1/incidents/{iid}", token=admin_token)[0] == 404
        assert invoke("GET", f"/api/v1/incidents/{iid}",
                      token=registered_user["token"])[0] == 404

    def test_disappears_from_the_lists(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        _delete(invoke, iid, admin_token)

        _, mine = invoke("GET", "/api/v1/incidents", token=registered_user["token"])
        _, queue = invoke("GET", "/api/v1/incidents/assigned", token=engineer_user["token"])
        _, all_of_them = invoke("GET", "/api/v1/admin/incidents", token=admin_token)

        assert iid not in [i["id"] for i in mine["incidents"]]
        assert iid not in [i["id"] for i in queue["incidents"]]
        assert iid not in [i["id"] for i in all_of_them["incidents"]]

    def test_comments_are_removed(self, invoke, registered_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        _comment(invoke, iid, registered_user["token"], "one")
        _comment(invoke, iid, admin_token, "two")

        status, body = _delete(invoke, iid, admin_token)

        assert status == 200
        assert body["comments_deleted"] == 2
        left = db.query_one(
            "SELECT COUNT(*) AS n FROM incident_comments WHERE incident_id = %s", (iid,)
        )
        assert left["n"] == 0

    def test_comment_endpoints_404(self, invoke, registered_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        _comment(invoke, iid, registered_user["token"], "gone soon")
        _delete(invoke, iid, admin_token)

        assert invoke("GET", f"/api/v1/incidents/{iid}/comments", token=admin_token)[0] == 404
        assert _comment(invoke, iid, admin_token)[0] == 404


class TestDeleteLeavesEverythingElseAlone:
    def test_other_incidents_untouched(self, invoke, registered_user, admin_token):
        doomed = _report(invoke, registered_user["token"], title="Delete me")
        keeper = _report(invoke, registered_user["token"], title="Keep me")
        _comment(invoke, keeper, registered_user["token"], "still here")

        _delete(invoke, doomed, admin_token)

        status, body = invoke("GET", f"/api/v1/incidents/{keeper}",
                              token=registered_user["token"])
        assert status == 200
        assert body["incident"]["title"] == "Keep me"

        _, comments = invoke("GET", f"/api/v1/incidents/{keeper}/comments",
                             token=registered_user["token"])
        assert [c["body"] for c in comments["comments"]] == ["still here"]

    def test_reporter_and_assignee_untouched(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        _delete(invoke, iid, admin_token)

        assert _exists("users", registered_user["user"]["id"])
        assert _exists("users", engineer_user["user"]["id"])
        # Still able to sign in, so the accounts are intact rather than merely present.
        assert invoke("GET", "/api/v1/auth/me", token=registered_user["token"])[0] == 200
        assert invoke("GET", "/api/v1/auth/me", token=engineer_user["token"])[0] == 200

    def test_facility_untouched(self, invoke, registered_user, admin_token, facility):
        iid = _report(invoke, registered_user["token"], seat_id=facility["seat_id"])

        _delete(invoke, iid, admin_token)

        assert _exists("buildings", facility["building_id"])
        assert _exists("floors", facility["floor_id"])
        assert _exists("seats", facility["seat_id"])

    def test_another_authors_comments_elsewhere_survive(
        self, invoke, registered_user, admin_token
    ):
        """The admin wrote on both; only the deleted incident's comment goes."""
        doomed = _report(invoke, registered_user["token"])
        keeper = _report(invoke, registered_user["token"])
        _comment(invoke, doomed, admin_token, "on the doomed one")
        _comment(invoke, keeper, admin_token, "on the surviving one")

        _delete(invoke, doomed, admin_token)

        _, body = invoke("GET", f"/api/v1/incidents/{keeper}/comments", token=admin_token)
        assert [c["body"] for c in body["comments"]] == ["on the surviving one"]


class TestAnalyticsAfterDeletion:
    """Analytics reads the incidents table directly, so a delete must show up
    with no cache to invalidate. These assert the exact movement."""

    def _summary(self, invoke, admin_token):
        _, body = invoke("GET", "/api/v1/admin/analytics", token=admin_token)
        return body

    def _building_count(self, summary, name):
        for row in summary["by_building"]:
            if row["building"] == name:
                return row["count"]
        return 0

    def test_every_figure_decreases(self, invoke, registered_user, admin_token):
        name = f"{TEST_BUILDING_PREFIX}{uuid.uuid4().hex[:8]}"
        building = db.query_one(
            "INSERT INTO buildings (name) VALUES (%s) RETURNING id", (name,)
        )
        floor = db.query_one(
            "INSERT INTO floors (building_id, name) VALUES (%s, %s) RETURNING id",
            (building["id"], "Floor 1"),
        )
        place = {"building_id": building["id"], "floor_id": floor["id"]}

        before = self._summary(invoke, admin_token)

        doomed = _report(invoke, registered_user["token"], category="PLUMBING", **place)
        _report(invoke, registered_user["token"], category="PLUMBING", **place)

        added = self._summary(invoke, admin_token)
        assert added["total"] == before["total"] + 2
        assert added["by_status"]["OPEN"] == before["by_status"]["OPEN"] + 2
        assert added["by_category"]["PLUMBING"] == before["by_category"]["PLUMBING"] + 2
        assert self._building_count(added, name) == 2

        _delete(invoke, doomed, admin_token)

        after = self._summary(invoke, admin_token)
        assert after["total"] == before["total"] + 1
        assert after["by_status"]["OPEN"] == before["by_status"]["OPEN"] + 1
        assert after["by_category"]["PLUMBING"] == before["by_category"]["PLUMBING"] + 1
        assert self._building_count(after, name) == 1

    def test_counts_still_reconcile(self, invoke, registered_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        _delete(invoke, iid, admin_token)

        summary = self._summary(invoke, admin_token)

        assert sum(summary["by_status"].values()) == summary["total"]
        assert sum(summary["by_category"].values()) == summary["total"]
        assert sum(r["count"] for r in summary["by_building"]) == summary["total"]

    def test_deleting_the_only_incident_in_a_building_removes_its_row(
        self, invoke, registered_user, admin_token
    ):
        name = f"{TEST_BUILDING_PREFIX}{uuid.uuid4().hex[:8]}"
        building = db.query_one(
            "INSERT INTO buildings (name) VALUES (%s) RETURNING id", (name,)
        )
        floor = db.query_one(
            "INSERT INTO floors (building_id, name) VALUES (%s, %s) RETURNING id",
            (building["id"], "Floor 1"),
        )
        iid = _report(invoke, registered_user["token"],
                      building_id=building["id"], floor_id=floor["id"])
        assert self._building_count(self._summary(invoke, admin_token), name) == 1

        _delete(invoke, iid, admin_token)

        # Grouped over incidents, so a building with none is simply not a row.
        assert self._building_count(self._summary(invoke, admin_token), name) == 0
        assert _exists("buildings", building["id"]), "the building itself must remain"
