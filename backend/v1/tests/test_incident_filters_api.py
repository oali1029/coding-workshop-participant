"""Tests for search and filtering on the admin incident list.

The admin list returns every incident in the database, including any the
developer created by hand, so most tests tag their own incidents with a random
token and search for that. Where a filter cannot be combined with the tag — the
reporter-name search, for instance — the test asserts both that its own incident
came back and that nothing came back which should not have.
"""

import uuid

from conftest import TEST_BUILDING_PREFIX, incident_payload

from app import db

ADMIN_LIST = "/api/v1/admin/incidents"


def _tag():
    """A token no other incident can contain."""
    return f"tag{uuid.uuid4().hex[:10]}"


def _report(invoke, token, **overrides):
    _, body = invoke("POST", "/api/v1/incidents", incident_payload(**overrides), token=token)
    return body["incident"]["id"]


def _search(invoke, admin_token, **query):
    status, body = invoke("GET", ADMIN_LIST, token=admin_token, query=query)
    return status, body


def _ids(body):
    return [row["id"] for row in body["incidents"]]


def _new_building():
    name = f"{TEST_BUILDING_PREFIX}{uuid.uuid4().hex[:8]}"
    building = db.query_one(
        "INSERT INTO buildings (name) VALUES (%s) RETURNING id", (name,)
    )
    floor = db.query_one(
        "INSERT INTO floors (building_id, name) VALUES (%s, %s) RETURNING id",
        (building["id"], "Floor 1"),
    )
    return {"building_id": building["id"], "floor_id": floor["id"]}


class TestFilterAccess:
    def test_employee_refused(self, invoke, registered_user):
        status, _ = invoke("GET", ADMIN_LIST,
                           token=registered_user["token"], query={"q": "anything"})
        assert status == 403

    def test_engineer_refused(self, invoke, engineer_user):
        status, _ = invoke("GET", ADMIN_LIST, token=engineer_user["token"],
                           query={"status": "OPEN"})
        assert status == 403

    def test_anonymous_refused(self, invoke):
        assert invoke("GET", ADMIN_LIST, query={"q": "anything"})[0] == 401


class TestSearch:
    def test_matches_title(self, invoke, admin_token, registered_user):
        tag = _tag()
        wanted = _report(invoke, registered_user["token"], title=f"Leak {tag}")
        _report(invoke, registered_user["token"], title="Unrelated fault")

        status, body = _search(invoke, admin_token, q=tag)

        assert status == 200
        assert _ids(body) == [wanted]

    def test_matches_description(self, invoke, admin_token, registered_user):
        tag = _tag()
        wanted = _report(invoke, registered_user["token"], description=f"Detail {tag}")

        _, body = _search(invoke, admin_token, q=tag)

        assert _ids(body) == [wanted]

    def test_is_case_insensitive(self, invoke, admin_token, registered_user):
        tag = _tag()
        wanted = _report(invoke, registered_user["token"], title=f"Leak {tag.upper()}")

        _, body = _search(invoke, admin_token, q=tag.lower())

        assert _ids(body) == [wanted]

    def test_matches_partial_word(self, invoke, admin_token, registered_user):
        tag = _tag()
        wanted = _report(invoke, registered_user["token"], title=f"Leak {tag}ing")

        _, body = _search(invoke, admin_token, q=tag)

        assert _ids(body) == [wanted]

    def test_matches_reporter_name(self, invoke, admin_token, registered_user):
        mine = _report(invoke, registered_user["token"])

        _, body = _search(invoke, admin_token, q="Test Person")

        assert mine in _ids(body)
        assert all(
            row["reporter_name"] == "Test Person" or row["assignee_name"] == "Test Person"
            for row in body["incidents"]
        )

    def test_matches_assignee_name(self, invoke, admin_token, registered_user, engineer_user):
        tag = _tag()
        iid = _report(invoke, registered_user["token"], title=f"Leak {tag}")
        invoke("PATCH", f"/api/v1/incidents/{iid}",
               {"assignee_id": engineer_user["user"]["id"]}, token=admin_token)

        _, body = _search(invoke, admin_token, q="Engineer Person")

        assert iid in _ids(body)

    def test_wildcards_are_literal(self, invoke, admin_token, registered_user):
        """"%" is a LIKE wildcard; searching for it must not match everything."""
        tag = _tag()
        wanted = _report(invoke, registered_user["token"], title=f"Cooling at 50% {tag}")
        _report(invoke, registered_user["token"], title=f"Cooling at 80 percent {tag}")

        _, body = _search(invoke, admin_token, q="50%")

        assert wanted in _ids(body)
        assert all("50%" in row["title"] for row in body["incidents"])

    def test_underscore_is_literal(self, invoke, admin_token, registered_user):
        tag = _tag()
        _report(invoke, registered_user["token"], title=f"Room a_b {tag}")

        _, body = _search(invoke, admin_token, q=f"a_b {tag}")

        assert len(body["incidents"]) == 1

        _, body = _search(invoke, admin_token, q=f"axb {tag}")

        assert body["incidents"] == []

    def test_no_match_returns_empty(self, invoke, admin_token, registered_user):
        _report(invoke, registered_user["token"])

        status, body = _search(invoke, admin_token, q=_tag())

        assert status == 200
        assert body["incidents"] == []

    def test_blank_search_is_ignored(self, invoke, admin_token, registered_user):
        mine = _report(invoke, registered_user["token"])

        _, body = _search(invoke, admin_token, q="   ")

        assert mine in _ids(body)


class TestFieldFilters:
    def test_by_status(self, invoke, admin_token, registered_user, engineer_user):
        tag = _tag()
        moved = _report(invoke, registered_user["token"], title=f"Moved {tag}")
        still_open = _report(invoke, registered_user["token"], title=f"Open {tag}")
        invoke("PATCH", f"/api/v1/incidents/{moved}",
               {"assignee_id": engineer_user["user"]["id"]}, token=admin_token)
        invoke("PATCH", f"/api/v1/incidents/{moved}", {"status": "IN_PROGRESS"},
               token=engineer_user["token"])

        _, body = _search(invoke, admin_token, q=tag, status="IN_PROGRESS")
        assert _ids(body) == [moved]

        _, body = _search(invoke, admin_token, q=tag, status="OPEN")
        assert _ids(body) == [still_open]

    def test_status_accepts_lowercase(self, invoke, admin_token, registered_user):
        tag = _tag()
        mine = _report(invoke, registered_user["token"], title=f"Leak {tag}")

        _, body = _search(invoke, admin_token, q=tag, status="open")

        assert _ids(body) == [mine]

    def test_by_category(self, invoke, admin_token, registered_user):
        tag = _tag()
        hvac = _report(invoke, registered_user["token"], title=f"Warm {tag}", category="HVAC")
        _report(invoke, registered_user["token"], title=f"Drip {tag}", category="PLUMBING")

        _, body = _search(invoke, admin_token, q=tag, category="HVAC")

        assert _ids(body) == [hvac]

    def test_by_building(self, invoke, admin_token, registered_user):
        tag = _tag()
        here = _new_building()
        wanted = _report(invoke, registered_user["token"], title=f"Leak {tag}",
                         building_id=here["building_id"], floor_id=here["floor_id"])
        _report(invoke, registered_user["token"], title=f"Other {tag}")

        _, body = _search(invoke, admin_token, q=tag, building=here["building_id"])

        assert _ids(body) == [wanted]

    def test_by_assignee(self, invoke, admin_token, registered_user, engineer_user):
        tag = _tag()
        assigned = _report(invoke, registered_user["token"], title=f"Mine {tag}")
        _report(invoke, registered_user["token"], title=f"Theirs {tag}")
        invoke("PATCH", f"/api/v1/incidents/{assigned}",
               {"assignee_id": engineer_user["user"]["id"]}, token=admin_token)

        _, body = _search(invoke, admin_token, q=tag, assignee=engineer_user["user"]["id"])

        assert _ids(body) == [assigned]

    def test_unassigned(self, invoke, admin_token, registered_user, engineer_user):
        tag = _tag()
        assigned = _report(invoke, registered_user["token"], title=f"Taken {tag}")
        waiting = _report(invoke, registered_user["token"], title=f"Waiting {tag}")
        invoke("PATCH", f"/api/v1/incidents/{assigned}",
               {"assignee_id": engineer_user["user"]["id"]}, token=admin_token)

        _, body = _search(invoke, admin_token, q=tag, assignee="unassigned")

        assert _ids(body) == [waiting]


class TestCombinedFilters:
    def test_all_conditions_must_hold(self, invoke, admin_token, registered_user, engineer_user):
        tag = _tag()
        here = _new_building()
        wanted = _report(invoke, registered_user["token"], title=f"Warm {tag}", category="HVAC",
                         building_id=here["building_id"], floor_id=here["floor_id"])
        # Each of these differs from `wanted` in exactly one filtered field.
        _report(invoke, registered_user["token"], title=f"Warm {tag}", category="PLUMBING",
                building_id=here["building_id"], floor_id=here["floor_id"])
        _report(invoke, registered_user["token"], title=f"Warm {tag}", category="HVAC")

        _, body = _search(invoke, admin_token, q=tag, category="HVAC",
                          building=here["building_id"], status="OPEN")

        assert _ids(body) == [wanted]

    def test_contradictory_filters_return_empty(self, invoke, admin_token, registered_user):
        tag = _tag()
        _report(invoke, registered_user["token"], title=f"Warm {tag}", category="HVAC")

        _, body = _search(invoke, admin_token, q=tag, category="PLUMBING")

        assert body["incidents"] == []

    def test_newest_first_is_preserved(self, invoke, admin_token, registered_user):
        tag = _tag()
        first = _report(invoke, registered_user["token"], title=f"One {tag}")
        second = _report(invoke, registered_user["token"], title=f"Two {tag}")

        _, body = _search(invoke, admin_token, q=tag)

        assert _ids(body) == [second, first]

    def test_no_filters_returns_everything(self, invoke, admin_token, registered_user):
        mine = _report(invoke, registered_user["token"])

        _, unfiltered = _search(invoke, admin_token)

        assert mine in _ids(unfiltered)


class TestInvalidFilters:
    def test_unknown_status(self, invoke, admin_token):
        status, body = _search(invoke, admin_token, status="ON_FIRE")

        assert status == 400
        assert body["details"]["field"] == "status"

    def test_unknown_category(self, invoke, admin_token):
        status, body = _search(invoke, admin_token, category="GHOSTS")

        assert status == 400
        assert body["details"]["field"] == "category"

    def test_non_numeric_building(self, invoke, admin_token):
        status, body = _search(invoke, admin_token, building="main")

        assert status == 400
        assert body["details"]["field"] == "building"

    def test_non_numeric_assignee(self, invoke, admin_token):
        status, body = _search(invoke, admin_token, assignee="someone")

        assert status == 400
        assert body["details"]["field"] == "assignee"

    def test_unknown_building_returns_empty(self, invoke, admin_token):
        """A valid-looking id that matches nothing is a normal empty result,
        not an error — the filter is a question, not an assertion."""
        status, body = _search(invoke, admin_token, building=999999)

        assert status == 200
        assert body["incidents"] == []
