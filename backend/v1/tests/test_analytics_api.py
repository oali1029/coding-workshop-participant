"""Tests for the Facility Admin analytics summary.

The suite shares one database with the developer's own data, so these tests
assert on *changes* rather than absolute totals: take a snapshot, create known
incidents, and check the figures moved by exactly the right amount. Asserting
"total == 3" would pass on a clean machine and fail on a used one.
"""

import uuid

from conftest import TEST_BUILDING_PREFIX, incident_payload

from app import db
from app.domains.analytics import ARCHIVED_BUILDING_LABEL
from app.domains.incidents import CATEGORIES, STATUSES


def _summary(invoke, admin_token):
    status, body = invoke("GET", "/api/v1/admin/analytics", token=admin_token)
    assert status == 200
    return body


def _building_count(summary, name):
    """The count for one building, or 0 when it has no incidents."""
    for row in summary["by_building"]:
        if row["building"] == name:
            return row["count"]
    return 0


def _report(invoke, token, **overrides):
    _, body = invoke("POST", "/api/v1/incidents", incident_payload(**overrides), token=token)
    return body["incident"]["id"]


def _new_building(name=None):
    """A building of this suite's own, so its counts start at zero."""
    name = name or f"{TEST_BUILDING_PREFIX}{uuid.uuid4().hex[:8]}"
    building = db.query_one(
        "INSERT INTO buildings (name) VALUES (%s) RETURNING id", (name,)
    )
    floor = db.query_one(
        "INSERT INTO floors (building_id, name) VALUES (%s, %s) RETURNING id",
        (building["id"], "Floor 1"),
    )
    return {"name": name, "building_id": building["id"], "floor_id": floor["id"]}


class TestAnalyticsAccess:
    def test_admin_allowed(self, invoke, admin_token):
        assert invoke("GET", "/api/v1/admin/analytics", token=admin_token)[0] == 200

    def test_employee_refused(self, invoke, registered_user):
        assert invoke("GET", "/api/v1/admin/analytics", token=registered_user["token"])[0] == 403

    def test_engineer_refused(self, invoke, engineer_user):
        assert invoke("GET", "/api/v1/admin/analytics", token=engineer_user["token"])[0] == 403

    def test_anonymous_refused(self, invoke):
        assert invoke("GET", "/api/v1/admin/analytics")[0] == 401


class TestAnalyticsShape:
    def test_every_status_present(self, invoke, admin_token):
        """Zero-filled, so the dashboard's cards do not appear and disappear."""
        summary = _summary(invoke, admin_token)

        assert set(summary["by_status"]) == set(STATUSES)

    def test_every_category_present(self, invoke, admin_token):
        summary = _summary(invoke, admin_token)

        assert set(summary["by_category"]) == set(CATEGORIES)

    def test_status_counts_sum_to_total(self, invoke, admin_token):
        summary = _summary(invoke, admin_token)

        assert sum(summary["by_status"].values()) == summary["total"]

    def test_category_counts_sum_to_total(self, invoke, admin_token):
        summary = _summary(invoke, admin_token)

        assert sum(summary["by_category"].values()) == summary["total"]

    def test_building_counts_sum_to_total(self, invoke, admin_token):
        """Detached incidents are bucketed, not dropped, so this must reconcile."""
        summary = _summary(invoke, admin_token)

        assert sum(row["count"] for row in summary["by_building"]) == summary["total"]


class TestAnalyticsCounts:
    def test_total_counts_new_incidents(self, invoke, admin_token, registered_user):
        before = _summary(invoke, admin_token)["total"]

        for _ in range(3):
            _report(invoke, registered_user["token"])

        assert _summary(invoke, admin_token)["total"] == before + 3

    def test_new_incidents_count_as_open(self, invoke, admin_token, registered_user):
        before = _summary(invoke, admin_token)["by_status"]

        for _ in range(2):
            _report(invoke, registered_user["token"])

        after = _summary(invoke, admin_token)["by_status"]

        assert after["OPEN"] == before["OPEN"] + 2
        assert after["RESOLVED"] == before["RESOLVED"]

    def test_status_change_moves_one_count(
        self, invoke, admin_token, registered_user, engineer_user
    ):
        iid = _report(invoke, registered_user["token"])
        invoke("PATCH", f"/api/v1/incidents/{iid}",
               {"assignee_id": engineer_user["user"]["id"]}, token=admin_token)
        before = _summary(invoke, admin_token)["by_status"]

        invoke("PATCH", f"/api/v1/incidents/{iid}", {"status": "IN_PROGRESS"},
               token=engineer_user["token"])

        after = _summary(invoke, admin_token)["by_status"]

        assert after["OPEN"] == before["OPEN"] - 1
        assert after["IN_PROGRESS"] == before["IN_PROGRESS"] + 1

    def test_categories_counted_separately(self, invoke, admin_token, registered_user):
        before = _summary(invoke, admin_token)["by_category"]

        _report(invoke, registered_user["token"], category="HVAC")
        _report(invoke, registered_user["token"], category="HVAC")
        _report(invoke, registered_user["token"], category="PLUMBING")

        after = _summary(invoke, admin_token)["by_category"]

        assert after["HVAC"] == before["HVAC"] + 2
        assert after["PLUMBING"] == before["PLUMBING"] + 1
        assert after["ELECTRICAL"] == before["ELECTRICAL"]

    def test_lowercase_category_is_normalised(self, invoke, admin_token, registered_user):
        """The API accepts "hvac"; analytics must not report a separate bucket."""
        before = _summary(invoke, admin_token)["by_category"]

        _report(invoke, registered_user["token"], category="hvac")

        after = _summary(invoke, admin_token)["by_category"]

        assert set(after) == set(CATEGORIES)
        assert after["HVAC"] == before["HVAC"] + 1


class TestAnalyticsByBuilding:
    def test_counts_per_building(self, invoke, admin_token, registered_user):
        here = _new_building()
        there = _new_building()

        for _ in range(2):
            _report(invoke, registered_user["token"],
                    building_id=here["building_id"], floor_id=here["floor_id"])
        _report(invoke, registered_user["token"],
                building_id=there["building_id"], floor_id=there["floor_id"])

        summary = _summary(invoke, admin_token)

        assert _building_count(summary, here["name"]) == 2
        assert _building_count(summary, there["name"]) == 1

    def test_empty_building_is_absent(self, invoke, admin_token):
        """GROUP BY over incidents, so a building nobody reported against is
        simply not a row — there is nothing to count."""
        unused = _new_building()

        assert _building_count(_summary(invoke, admin_token), unused["name"]) == 0

    def test_ordered_by_count_descending(self, invoke, admin_token):
        counts = [row["count"] for row in _summary(invoke, admin_token)["by_building"]]

        assert counts == sorted(counts, reverse=True)

    def test_deleted_building_moves_to_archived(self, invoke, admin_token, registered_user):
        """The incident survives the building; its count must survive too."""
        doomed = _new_building()
        _report(invoke, registered_user["token"],
                building_id=doomed["building_id"], floor_id=doomed["floor_id"])

        before = _summary(invoke, admin_token)
        assert _building_count(before, doomed["name"]) == 1

        invoke("DELETE", f"/api/v1/buildings/{doomed['building_id']}", token=admin_token)

        after = _summary(invoke, admin_token)

        assert after["total"] == before["total"]
        assert _building_count(after, doomed["name"]) == 0
        assert _building_count(after, ARCHIVED_BUILDING_LABEL) == (
            _building_count(before, ARCHIVED_BUILDING_LABEL) + 1
        )
