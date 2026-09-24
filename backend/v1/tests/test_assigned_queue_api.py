"""Regression tests for the engineer's queue with no filters — "Any Status".

Filtered requests to /incidents/assigned were already covered; the unfiltered
one was not, and that is the state the page opens in. These tests pin down the
contract the frontend depends on: the same JSON shape whether filters are
present, absent as empty strings, or absent from the event altogether, and an
empty queue as an empty list rather than null or a bodiless response.

The "no query parameters at all" case builds its own Lambda event, because a
real Function URL omits ``queryStringParameters`` entirely when the URL carries
no query string, while the ``invoke`` fixture always sends a dict.
"""

import json

from conftest import incident_payload

ASSIGNED_LIST = "/api/v1/incidents/assigned"

# What the page sends before the client drops empty values: every filter present
# and blank, which must mean exactly the same as sending nothing.
ANY_STATUS_QUERY = {
    "q": "",
    "status": "",
    "category": "",
    "priority": "",
    "building": "",
    "assignee": "",
}


def _report(invoke, token, **overrides):
    _, body = invoke("POST", "/api/v1/incidents", incident_payload(**overrides), token=token)
    return body["incident"]["id"]


def _assign(invoke, admin_token, incident_id, assignee_id):
    return invoke("PATCH", f"/api/v1/incidents/{incident_id}",
                  {"assignee_id": assignee_id}, token=admin_token)


def _set_status(invoke, token, incident_id, status):
    return invoke("PATCH", f"/api/v1/incidents/{incident_id}",
                  {"status": status}, token=token)


def _ids(body):
    return [row["id"] for row in body["incidents"]]


def _call_without_query_string(token):
    """Invoke the handler with no ``queryStringParameters`` key at all.

    This is the event a Lambda Function URL really produces for
    ``GET /api/v1/incidents/assigned``, and it is the request the Assigned
    Incidents page makes on open.
    """
    from function import handler

    event = {
        "requestContext": {"http": {"method": "GET", "path": ASSIGNED_LIST}},
        "headers": {"authorization": f"Bearer {token}"},
        "body": None,
    }
    response = handler(event)
    return response, json.loads(response["body"]) if response["body"] else None


class TestAnyStatus:
    def test_no_query_string_returns_the_whole_queue(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        first = _report(invoke, registered_user["token"], title="Queue one")
        second = _report(invoke, registered_user["token"], title="Queue two")
        for incident_id in (first, second):
            _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])

        response, body = _call_without_query_string(engineer_user["token"])

        assert response["statusCode"] == 200
        assert body is not None
        assert sorted(_ids(body)) == sorted([first, second])

    def test_empty_filters_mean_the_same_as_no_filters(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        assigned = _report(invoke, registered_user["token"], title="Blank filters")
        _assign(invoke, admin_token, assigned, engineer_user["user"]["id"])

        _, blank = invoke("GET", ASSIGNED_LIST, token=engineer_user["token"],
                          query=ANY_STATUS_QUERY)
        _, absent = _call_without_query_string(engineer_user["token"])

        assert _ids(blank) == _ids(absent)

    def test_empty_queue_is_an_empty_list(self, invoke, engineer_user):
        """A new engineer holds nothing, and must still get incidents: []."""
        response, body = _call_without_query_string(engineer_user["token"])

        assert response["statusCode"] == 200
        assert body["incidents"] == []

    def test_response_always_carries_a_body(self, invoke, engineer_user):
        """Never 204 and never an empty body: the client reads .incidents."""
        response, body = _call_without_query_string(engineer_user["token"])

        assert response["statusCode"] == 200
        assert response["body"] != ""
        assert response["headers"]["Content-Type"] == "application/json"
        assert isinstance(body, dict) and isinstance(body["incidents"], list)

    def test_shape_is_identical_filtered_and_unfiltered(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        assigned = _report(invoke, registered_user["token"], title="Shape check")
        _assign(invoke, admin_token, assigned, engineer_user["user"]["id"])

        _, unfiltered = _call_without_query_string(engineer_user["token"])
        _, filtered = invoke("GET", ASSIGNED_LIST, token=engineer_user["token"],
                             query={"status": "OPEN"})

        assert list(unfiltered) == list(filtered) == ["incidents"]
        assert set(unfiltered["incidents"][0]) == set(filtered["incidents"][0])

    def test_another_engineers_work_stays_out(
        self, invoke, registered_user, engineer_user, second_engineer, admin_token
    ):
        """Any Status removes the status restriction, never the scope."""
        mine = _report(invoke, registered_user["token"], title="Mine")
        theirs = _report(invoke, registered_user["token"], title="Theirs")
        _assign(invoke, admin_token, mine, engineer_user["user"]["id"])
        _assign(invoke, admin_token, theirs, second_engineer["user"]["id"])

        _, body = _call_without_query_string(engineer_user["token"])

        assert _ids(body) == [mine]

    def test_unassigned_work_stays_out(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        nobodys = _report(invoke, registered_user["token"], title="Nobody holds this")
        mine = _report(invoke, registered_user["token"], title="I hold this")
        _assign(invoke, admin_token, mine, engineer_user["user"]["id"])

        _, body = _call_without_query_string(engineer_user["token"])

        assert _ids(body) == [mine]
        assert nobodys not in _ids(body)


class TestAnyStatusShowsEveryStatus:
    def test_includes_statuses_a_status_filter_would_exclude(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """The whole point of Any Status: no status is left out."""
        engineer = engineer_user["user"]["id"]
        token = engineer_user["token"]

        open_one = _report(invoke, registered_user["token"], title="Still open")
        in_progress = _report(invoke, registered_user["token"], title="Being worked")
        blocked = _report(invoke, registered_user["token"], title="Stuck")
        for incident_id in (open_one, in_progress, blocked):
            _assign(invoke, admin_token, incident_id, engineer)

        _set_status(invoke, token, in_progress, "IN_PROGRESS")
        _set_status(invoke, token, blocked, "BLOCKED")

        _, body = _call_without_query_string(token)

        assert sorted(_ids(body)) == sorted([open_one, in_progress, blocked])

    def test_status_filter_then_back_to_any_status(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """Clearing the filter restores the full queue, not the filtered one."""
        engineer = engineer_user["user"]["id"]
        token = engineer_user["token"]

        open_one = _report(invoke, registered_user["token"], title="Open item")
        working = _report(invoke, registered_user["token"], title="Working item")
        for incident_id in (open_one, working):
            _assign(invoke, admin_token, incident_id, engineer)
        _set_status(invoke, token, working, "IN_PROGRESS")

        _, only_open = invoke("GET", ASSIGNED_LIST, token=token, query={"status": "OPEN"})
        _, only_working = invoke("GET", ASSIGNED_LIST, token=token,
                                 query={"status": "IN_PROGRESS"})
        _, cleared = invoke("GET", ASSIGNED_LIST, token=token, query=ANY_STATUS_QUERY)

        assert _ids(only_open) == [open_one]
        assert _ids(only_working) == [working]
        assert sorted(_ids(cleared)) == sorted([open_one, working])


class TestOtherFiltersWithAnyStatus:
    def test_search_with_no_status(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        wanted = _report(invoke, registered_user["token"], title="Flickering lamp")
        other = _report(invoke, registered_user["token"], title="Dripping pipe")
        for incident_id in (wanted, other):
            _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])

        _, body = invoke("GET", ASSIGNED_LIST, token=engineer_user["token"],
                         query={**ANY_STATUS_QUERY, "q": "Flickering lamp"})

        assert _ids(body) == [wanted]

    def test_priority_with_any_status(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        high = _report(invoke, registered_user["token"], priority="HIGH")
        low = _report(invoke, registered_user["token"], priority="LOW")
        for incident_id in (high, low):
            _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])

        _, body = invoke("GET", ASSIGNED_LIST, token=engineer_user["token"],
                         query={**ANY_STATUS_QUERY, "priority": "HIGH"})

        assert _ids(body) == [high]

    def test_category_with_any_status(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        hvac = _report(invoke, registered_user["token"], category="HVAC")
        plumbing = _report(invoke, registered_user["token"], category="PLUMBING")
        for incident_id in (hvac, plumbing):
            _assign(invoke, admin_token, incident_id, engineer_user["user"]["id"])

        _, body = invoke("GET", ASSIGNED_LIST, token=engineer_user["token"],
                         query={**ANY_STATUS_QUERY, "category": "HVAC"})

        assert _ids(body) == [hvac]

    def test_building_with_any_status(
        self, invoke, registered_user, engineer_user, admin_token, facility
    ):
        mine = _report(invoke, registered_user["token"], title="In the test building")
        _assign(invoke, admin_token, mine, engineer_user["user"]["id"])

        _, body = invoke("GET", ASSIGNED_LIST, token=engineer_user["token"],
                         query={**ANY_STATUS_QUERY, "building": facility["building_id"]})

        assert mine in _ids(body)


class TestAnyStatusAccess:
    def test_employee_refused(self, invoke, registered_user):
        response, _ = _call_without_query_string(registered_user["token"])
        assert response["statusCode"] == 403

    def test_admin_refused(self, invoke, admin_token):
        response, _ = _call_without_query_string(admin_token)
        assert response["statusCode"] == 403

    def test_anonymous_refused(self, invoke):
        status, _ = invoke("GET", ASSIGNED_LIST)
        assert status == 401
