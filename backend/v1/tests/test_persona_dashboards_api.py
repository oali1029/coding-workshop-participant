"""Tests for the Employee and Engineer dashboards, and per-persona filtering.

The point of these endpoints is scope. Every test here is really asking the same
question — can this persona see a number, or a row, that belongs to somebody
else? — so most of them set up two users and check the boundary between them.
"""

from conftest import incident_payload

MY_LIST = "/api/v1/incidents"
MY_SUMMARY = "/api/v1/incidents/summary"
ASSIGNED_LIST = "/api/v1/incidents/assigned"
ASSIGNED_SUMMARY = "/api/v1/incidents/assigned/summary"
ADMIN_LIST = "/api/v1/admin/incidents"


def _report(invoke, token, **overrides):
    _, body = invoke("POST", MY_LIST, incident_payload(**overrides), token=token)
    return body["incident"]["id"]


def _assign(invoke, admin_token, incident_id, assignee_id):
    return invoke("PATCH", f"/api/v1/incidents/{incident_id}",
                  {"assignee_id": assignee_id}, token=admin_token)


def _ids(body):
    return [row["id"] for row in body["incidents"]]


class TestEmployeeDashboard:
    def test_counts_only_my_incidents(self, invoke, registered_user, second_user):
        _report(invoke, registered_user["token"])
        _report(invoke, registered_user["token"])
        _report(invoke, second_user["token"])

        _, mine = invoke("GET", MY_SUMMARY, token=registered_user["token"])
        _, theirs = invoke("GET", MY_SUMMARY, token=second_user["token"])

        assert mine["total"] == 2
        assert mine["by_status"]["OPEN"] == 2
        assert theirs["total"] == 1

    def test_zero_filled_breakdowns(self, invoke, registered_user):
        _, body = invoke("GET", MY_SUMMARY, token=registered_user["token"])

        assert set(body["by_status"]) == {
            "OPEN", "IN_PROGRESS", "BLOCKED", "RESOLVED", "CLOSED",
        }
        assert set(body["by_priority"]) == {"LOW", "MEDIUM", "HIGH"}

    def test_priority_breakdown_is_accurate(self, invoke, registered_user):
        _report(invoke, registered_user["token"], priority="HIGH")
        _report(invoke, registered_user["token"], priority="HIGH")
        _report(invoke, registered_user["token"], priority="LOW")

        _, body = invoke("GET", MY_SUMMARY, token=registered_user["token"])

        assert body["by_priority"]["HIGH"] == 2
        assert body["by_priority"]["LOW"] == 1
        assert body["by_priority"]["MEDIUM"] == 0

    def test_counts_reconcile(self, invoke, registered_user):
        for _ in range(3):
            _report(invoke, registered_user["token"])

        _, body = invoke("GET", MY_SUMMARY, token=registered_user["token"])

        assert sum(body["by_status"].values()) == body["total"]
        assert sum(body["by_priority"].values()) == body["total"]
        assert sum(body["by_category"].values()) == body["total"]

    def test_new_account_sees_zeroes(self, invoke, registered_user):
        _, body = invoke("GET", MY_SUMMARY, token=registered_user["token"])

        assert body["total"] == 0
        assert body["by_status"]["OPEN"] == 0

    def test_assigned_work_is_not_counted(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """The employee dashboard is about what you reported, not what you hold."""
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        _, body = invoke("GET", MY_SUMMARY, token=engineer_user["token"])

        assert body["total"] == 0

    def test_requires_authentication(self, invoke):
        assert invoke("GET", MY_SUMMARY)[0] == 401


class TestEngineerDashboard:
    def test_counts_only_my_assignments(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        mine = _report(invoke, registered_user["token"])
        _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, mine, engineer_user["user"]["id"])

        _, body = invoke("GET", ASSIGNED_SUMMARY, token=engineer_user["token"])

        assert body["total"] == 1

    def test_reflects_status_changes(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        invoke("PATCH", f"/api/v1/incidents/{iid}", {"status": "IN_PROGRESS"},
               token=engineer_user["token"])

        _, body = invoke("GET", ASSIGNED_SUMMARY, token=engineer_user["token"])

        assert body["by_status"]["IN_PROGRESS"] == 1
        assert body["by_status"]["OPEN"] == 0

    def test_shows_priority_distribution(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        high = _report(invoke, registered_user["token"], priority="HIGH")
        low = _report(invoke, registered_user["token"], priority="LOW")
        _assign(invoke, admin_token, high, engineer_user["user"]["id"])
        _assign(invoke, admin_token, low, engineer_user["user"]["id"])

        _, body = invoke("GET", ASSIGNED_SUMMARY, token=engineer_user["token"])

        assert body["by_priority"]["HIGH"] == 1
        assert body["by_priority"]["LOW"] == 1

    def test_own_report_is_not_counted_unless_assigned(
        self, invoke, engineer_user
    ):
        """An engineer who reports a fault has not thereby been given the work."""
        _report(invoke, engineer_user["token"])

        _, body = invoke("GET", ASSIGNED_SUMMARY, token=engineer_user["token"])

        assert body["total"] == 0

    def test_employee_refused(self, invoke, registered_user):
        assert invoke("GET", ASSIGNED_SUMMARY, token=registered_user["token"])[0] == 403

    def test_admin_refused(self, invoke, admin_token):
        """Admins are never assignees, so the queue would always be empty."""
        assert invoke("GET", ASSIGNED_SUMMARY, token=admin_token)[0] == 403

    def test_requires_authentication(self, invoke):
        assert invoke("GET", ASSIGNED_SUMMARY)[0] == 401


class TestEmployeeFilters:
    def test_filters_cannot_reach_another_employee(
        self, invoke, registered_user, second_user
    ):
        """The scope clause comes first; a filter can only ever narrow it."""
        theirs = _report(invoke, second_user["token"], title="Their leak")
        mine = _report(invoke, registered_user["token"], title="My leak")

        _, body = invoke("GET", MY_LIST, token=registered_user["token"],
                         query={"q": "leak"})

        assert _ids(body) == [mine]
        assert theirs not in _ids(body)

    def test_by_status(self, invoke, registered_user, engineer_user, admin_token):
        moved = _report(invoke, registered_user["token"])
        still_open = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, moved, engineer_user["user"]["id"])
        invoke("PATCH", f"/api/v1/incidents/{moved}", {"status": "IN_PROGRESS"},
               token=engineer_user["token"])

        _, body = invoke("GET", MY_LIST, token=registered_user["token"],
                         query={"status": "IN_PROGRESS"})
        assert _ids(body) == [moved]

        _, body = invoke("GET", MY_LIST, token=registered_user["token"],
                         query={"status": "OPEN"})
        assert _ids(body) == [still_open]

    def test_by_priority(self, invoke, registered_user):
        high = _report(invoke, registered_user["token"], priority="HIGH")
        _report(invoke, registered_user["token"], priority="LOW")

        _, body = invoke("GET", MY_LIST, token=registered_user["token"],
                         query={"priority": "HIGH"})

        assert _ids(body) == [high]

    def test_by_category(self, invoke, registered_user):
        hvac = _report(invoke, registered_user["token"], category="HVAC")
        _report(invoke, registered_user["token"], category="PLUMBING")

        _, body = invoke("GET", MY_LIST, token=registered_user["token"],
                         query={"category": "HVAC"})

        assert _ids(body) == [hvac]

    def test_by_building(self, invoke, registered_user, facility):
        mine = _report(invoke, registered_user["token"])

        _, body = invoke("GET", MY_LIST, token=registered_user["token"],
                         query={"building": facility["building_id"]})
        assert mine in _ids(body)

        _, body = invoke("GET", MY_LIST, token=registered_user["token"],
                         query={"building": 999999})
        assert body["incidents"] == []

    def test_assignee_filter_is_ignored(
        self, invoke, registered_user, second_user, engineer_user, admin_token
    ):
        """Honouring it could only ever be a way to probe other people's work."""
        theirs = _report(invoke, second_user["token"])
        mine = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, theirs, engineer_user["user"]["id"])

        _, body = invoke("GET", MY_LIST, token=registered_user["token"],
                         query={"assignee": engineer_user["user"]["id"]})

        assert _ids(body) == [mine]

    def test_invalid_value_rejected(self, invoke, registered_user):
        status, body = invoke("GET", MY_LIST, token=registered_user["token"],
                              query={"priority": "URGENT"})

        assert status == 400
        assert body["details"]["field"] == "priority"


class TestEngineerFilters:
    def test_filters_cannot_reach_unassigned_work(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        unassigned = _report(invoke, registered_user["token"], title="Nobody has this")
        mine = _report(invoke, registered_user["token"], title="Nobody else has this")
        _assign(invoke, admin_token, mine, engineer_user["user"]["id"])

        _, body = invoke("GET", ASSIGNED_LIST, token=engineer_user["token"],
                         query={"q": "has this"})

        assert _ids(body) == [mine]
        assert unassigned not in _ids(body)

    def test_cannot_reach_another_engineers_work(
        self, invoke, registered_user, engineer_user, second_engineer, admin_token
    ):
        theirs = _report(invoke, registered_user["token"], title="Shared word")
        mine = _report(invoke, registered_user["token"], title="Shared word")
        _assign(invoke, admin_token, theirs, second_engineer["user"]["id"])
        _assign(invoke, admin_token, mine, engineer_user["user"]["id"])

        _, body = invoke("GET", ASSIGNED_LIST, token=engineer_user["token"],
                         query={"q": "Shared word"})

        assert _ids(body) == [mine]

    def test_by_priority(self, invoke, registered_user, engineer_user, admin_token):
        high = _report(invoke, registered_user["token"], priority="HIGH")
        low = _report(invoke, registered_user["token"], priority="LOW")
        _assign(invoke, admin_token, high, engineer_user["user"]["id"])
        _assign(invoke, admin_token, low, engineer_user["user"]["id"])

        _, body = invoke("GET", ASSIGNED_LIST, token=engineer_user["token"],
                         query={"priority": "HIGH"})

        assert _ids(body) == [high]

    def test_by_category_and_status_combine(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        wanted = _report(invoke, registered_user["token"], category="HVAC")
        other = _report(invoke, registered_user["token"], category="PLUMBING")
        for iid in (wanted, other):
            _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        _, body = invoke("GET", ASSIGNED_LIST, token=engineer_user["token"],
                         query={"category": "HVAC", "status": "OPEN"})

        assert _ids(body) == [wanted]


class TestAdminPriorityFilter:
    def test_by_priority(self, invoke, registered_user, admin_token):
        high = _report(invoke, registered_user["token"], title="Urgent one", priority="HIGH")
        _report(invoke, registered_user["token"], title="Urgent one", priority="LOW")

        _, body = invoke("GET", ADMIN_LIST, token=admin_token,
                         query={"q": "Urgent one", "priority": "HIGH"})

        assert _ids(body) == [high]

    def test_combines_with_other_filters(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        wanted = _report(invoke, registered_user["token"], title="Combo",
                         priority="HIGH", category="HVAC")
        _report(invoke, registered_user["token"], title="Combo",
                priority="HIGH", category="PLUMBING")
        _report(invoke, registered_user["token"], title="Combo",
                priority="LOW", category="HVAC")

        _, body = invoke("GET", ADMIN_LIST, token=admin_token,
                         query={"q": "Combo", "priority": "HIGH", "category": "HVAC",
                                "assignee": "unassigned"})

        assert _ids(body) == [wanted]

    def test_invalid_priority_rejected(self, invoke, admin_token):
        status, body = invoke("GET", ADMIN_LIST, token=admin_token,
                              query={"priority": "URGENT"})

        assert status == 400
        assert body["details"]["field"] == "priority"
