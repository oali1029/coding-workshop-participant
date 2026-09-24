"""Tests for the demo seeder.

Two concerns are covered here, and the first one matters far more than the
second: that seeding cannot be reached over HTTP, and that removing the demo
dataset cannot remove anything else.

These tests deliberately do NOT run a full seed. A complete run creates a
hundred incidents in the same database the developer is demonstrating from, and
a test suite that quietly replaced somebody's prepared demo dataset would be
worse than no test at all. The event classification and the plan are verified
directly, and cleanup is verified against a manifest the test itself controls.
"""

import json

import pytest

from app import demo_data, demo_seed
from conftest import TEST_FACILITY, _json, _make_request  # noqa: F401


# ---------------------------------------------------------------------------
# Event classification — the boundary that keeps seeding off the internet
# ---------------------------------------------------------------------------
def _function_url_event(method="GET", path="/health", body=None):
    """The event shape AWS builds for a Lambda Function URL request."""
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {"content-type": "application/json"},
        "requestContext": {"http": {"method": method, "path": path}},
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
    }


def _direct_event(action="status", **extra):
    payload = {"marker": demo_seed.DIRECT_INVOKE_MARKER, "action": action}
    payload.update(extra)
    return {demo_seed.DIRECT_INVOKE_KEY: payload}


def test_function_url_event_is_classified_as_http():
    assert demo_seed.classify_event(_function_url_event()) == demo_seed.EVENT_HTTP


def test_api_gateway_v1_event_is_classified_as_http():
    event = {
        "httpMethod": "POST",
        "path": "/api/v1/incidents",
        "headers": {},
        "body": "{}",
        "requestContext": {},
    }
    assert demo_seed.classify_event(event) == demo_seed.EVENT_HTTP


def test_direct_event_with_the_marker_is_recognised():
    assert demo_seed.classify_event(_direct_event()) == demo_seed.EVENT_DIRECT


def test_marker_alongside_http_fields_is_ambiguous_and_refused():
    """A crafted event that looks like both is never resolved in favour of seeding."""
    event = _function_url_event()
    event.update(_direct_event("seed"))
    assert demo_seed.classify_event(event) == demo_seed.EVENT_AMBIGUOUS


@pytest.mark.parametrize(
    "payload",
    [
        {"marker": "wrong-marker", "action": "seed"},
        {"action": "seed"},
        {"marker": demo_seed.DIRECT_INVOKE_MARKER.upper(), "action": "seed"},
        "not-a-dict",
        None,
        42,
    ],
)
def test_an_event_without_the_exact_marker_is_not_a_direct_invocation(payload):
    event = {demo_seed.DIRECT_INVOKE_KEY: payload}
    assert demo_seed.classify_event(event) == demo_seed.EVENT_HTTP


def test_a_non_dict_event_is_not_a_direct_invocation():
    assert demo_seed.classify_event("seed please") == demo_seed.EVENT_HTTP
    assert demo_seed.classify_event(None) == demo_seed.EVENT_HTTP


# ---------------------------------------------------------------------------
# The handler itself
# ---------------------------------------------------------------------------
def test_a_normal_http_request_still_reaches_the_router(invoke):
    """The existing path is unchanged by the branch added in front of it."""
    status, payload = invoke("GET", "/api/v1/health")
    assert status == 200
    # The health endpoint proves it reached the database, which is what shows
    # the request went all the way through the unchanged path.
    assert payload["ok"] is True
    assert payload["database"]


def test_an_http_request_carrying_the_seed_marker_in_its_body_cannot_seed(monkeypatch):
    """THE CENTRAL SECURITY TEST.

    A caller posting the seed payload to the public URL must not reach the
    seeder. The marker arrives inside the body string, never at the top level of
    the event, so classification never sees it.
    """
    from function import handler

    def explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("the seeder was reachable over HTTP")

    monkeypatch.setattr(demo_seed, "run", explode)
    monkeypatch.setattr(demo_seed, "handle_direct_invoke", explode)

    event = _function_url_event(
        "POST",
        "/api/v1/incidents",
        body=_direct_event("seed", password="irrelevant"),
    )
    response = handler(event)

    # Refused as an ordinary request would be — it is not a real endpoint for
    # an unauthenticated caller — and crucially not as a seed invocation.
    assert response["statusCode"] in (401, 404, 405)


def test_the_handler_refuses_an_ambiguous_event(monkeypatch):
    from function import handler

    def explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("an ambiguous event reached the seeder")

    monkeypatch.setattr(demo_seed, "handle_direct_invoke", explode)

    event = _function_url_event()
    event.update(_direct_event("seed"))
    response = handler(event)

    assert response["statusCode"] == 400


def test_a_direct_invocation_with_an_unknown_action_does_nothing(monkeypatch):
    def explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("an unknown action was executed")

    monkeypatch.setattr(demo_seed, "run", explode)

    result = demo_seed.handle_direct_invoke(_direct_event("drop-everything"))
    assert result["ok"] is False
    assert "action must be one of" in result["error"]


def test_seeding_without_a_password_is_refused():
    """Reported as a failed action rather than raising, and nothing is created."""
    result = demo_seed.handle_direct_invoke(_direct_event("seed"))
    assert result["ok"] is False
    assert "password" in result["error"].lower()


# ---------------------------------------------------------------------------
# The dataset plan
# ---------------------------------------------------------------------------
def test_the_plan_is_deterministic():
    """Two runs produce the same dataset, so a rehearsed demo stays the same."""
    first = demo_data.build_plan()
    second = demo_data.build_plan()

    assert [i.title for i in first.incidents] == [i.title for i in second.incidents]
    assert [i.timeline.created for i in first.incidents] == [
        i.timeline.created for i in second.incidents
    ]


def test_the_plan_matches_the_agreed_shape():
    plan = demo_data.build_plan()

    assert len(plan.buildings) == 5
    assert plan.floor_count == 15
    assert plan.seat_count == 40
    assert len(plan.engineers) == 10
    assert len(plan.employees) == 8
    assert 80 <= len(plan.incidents) <= 120
    assert plan.comment_count > 40

    statuses = {i.status for i in plan.incidents}
    assert statuses == {"OPEN", "IN_PROGRESS", "BLOCKED", "RESOLVED", "CLOSED"}
    assert {i.priority for i in plan.incidents} == {"LOW", "MEDIUM", "HIGH"}
    assert len({i.category for i in plan.incidents}) == 6

    assert sum(1 for i in plan.incidents if i.escalation_reason) >= 5
    assert all(i.blocked_reason for i in plan.incidents if i.status == "BLOCKED")


def test_the_plan_produces_exactly_the_intended_recurring_clusters():
    """Reproduces the grouping rule Operational Insights uses, so a change to
    the dataset that would add or lose a cluster fails here rather than on the
    dashboard mid-presentation."""
    plan = demo_data.build_plan()

    groups: dict[tuple, int] = {}
    for incident in plan.incidents:
        key = (incident.category, incident.building, incident.floor, incident.seat)
        groups[key] = groups.get(key, 0) + 1

    from app.domains.analytics import RECURRING_THRESHOLD

    clusters = {key: n for key, n in groups.items() if n >= RECURRING_THRESHOLD}
    assert len(clusters) == demo_data.recurring_cluster_count() == 4

    # One cluster is pinned to a specific desk; the rest are shared spaces.
    assert any(key[3] is not None for key in clusters)
    assert any(key[3] is None for key in clusters)

    # Four different buildings, so the estate breakdown has variety.
    assert len({key[1] for key in clusters}) == 4


def test_every_incident_falls_inside_the_analytics_window():
    from app.domains.analytics import OPERATIONAL_WINDOW_DAYS

    plan = demo_data.build_plan()
    window = OPERATIONAL_WINDOW_DAYS * demo_data.DAY

    for incident in plan.incidents:
        assert 0 < incident.timeline.created < window


def test_lifecycle_timestamps_are_ordered_and_status_appropriate():
    """The backdating pass can only produce believable averages if the plan it
    applies is itself coherent."""
    plan = demo_data.build_plan()

    for incident in plan.incidents:
        timeline = incident.timeline
        reached = [
            value
            for value in (
                timeline.created,
                timeline.acknowledged,
                timeline.assigned,
                timeline.resolved,
                timeline.closed,
            )
            if value is not None
        ]
        # Stored as "seconds ago", so a later milestone is a smaller number.
        assert reached == sorted(reached, reverse=True)

        if incident.status in ("OPEN", "IN_PROGRESS", "BLOCKED"):
            assert timeline.resolved is None
            assert timeline.closed is None
        if incident.status == "RESOLVED":
            assert timeline.resolved is not None and timeline.closed is None
        if incident.status == "CLOSED":
            assert timeline.closed is not None


def test_resolution_times_vary_rather_than_following_one_pattern():
    """A demo where every ticket took the same time makes the lifecycle panel
    look manufactured."""
    plan = demo_data.build_plan()

    durations = [
        incident.timeline.created - incident.timeline.resolved
        for incident in plan.incidents
        if incident.timeline.resolved is not None
    ]

    assert len(durations) > 40
    assert min(durations) < 6 * demo_data.HOUR, "nothing was fixed quickly"
    assert max(durations) > 2 * demo_data.DAY, "nothing took more than a couple of days"


def test_engineer_workload_is_deliberately_uneven():
    plan = demo_data.build_plan()

    active: dict[int, int] = {}
    for incident in plan.incidents:
        if incident.status != "CLOSED" and incident.engineer is not None and incident.engineer >= 0:
            active[incident.engineer] = active.get(incident.engineer, 0) + 1

    loads = sorted(active.values(), reverse=True)
    assert loads[0] >= 5, "no engineer is visibly overloaded"
    assert len(active) < len(plan.engineers), "every engineer has work, so nobody looks free"
    assert plan.unavailable_engineers, "no engineer is marked unavailable"


# ---------------------------------------------------------------------------
# Cleanup scoping
# ---------------------------------------------------------------------------
@pytest.fixture
def isolated_manifest():
    """Swap the real manifest out for the duration of one test.

    Without this, a cleanup test would read whatever demo dataset the developer
    currently has seeded and delete it.
    """
    from app import db

    saved = db.query_one(
        "SELECT value FROM app_config WHERE key = %s", (demo_seed.MANIFEST_KEY,)
    )
    db.execute("DELETE FROM app_config WHERE key = %s", (demo_seed.MANIFEST_KEY,))

    yield

    db.execute("DELETE FROM app_config WHERE key = %s", (demo_seed.MANIFEST_KEY,))
    if saved is not None:
        db.execute(
            "INSERT INTO app_config (key, value) VALUES (%s, %s)",
            (demo_seed.MANIFEST_KEY, saved["value"]),
        )


def test_clean_removes_only_rows_named_in_the_manifest(
    isolated_manifest, invoke, registered_user, facility
):
    """Two identical incidents, one listed in the manifest and one not. Only the
    listed one may disappear."""
    from app import db
    from conftest import incident_payload

    token = registered_user["token"]

    status, owned = invoke("POST", "/api/v1/incidents", incident_payload(), token=token)
    assert status == 201
    status, untouched = invoke("POST", "/api/v1/incidents", incident_payload(), token=token)
    assert status == 201

    owned_id = owned["incident"]["id"]
    untouched_id = untouched["incident"]["id"]

    manifest = demo_seed._empty_manifest()
    manifest["incidents"] = [owned_id]
    demo_seed._save_manifest(manifest)

    result = demo_seed.clean()

    assert result["found"] is True
    assert result["removed"]["incidents"] == 1

    assert db.query_one("SELECT id FROM incidents WHERE id = %s", (owned_id,)) is None
    assert db.query_one("SELECT id FROM incidents WHERE id = %s", (untouched_id,)) is not None

    # The shared test facility was never in the manifest and must survive.
    assert db.query_one(
        "SELECT id FROM buildings WHERE id = %s", (facility["building_id"],)
    ) is not None

    db.execute("DELETE FROM incidents WHERE id = %s", (untouched_id,))


def test_clean_reports_nothing_when_no_dataset_is_present(isolated_manifest):
    result = demo_seed.clean()
    assert result["found"] is False
    assert result["removed"] == {}


def test_clean_keeps_a_demo_account_that_still_has_real_work(
    isolated_manifest, invoke, registered_user, facility
):
    """A demo user who reported an incident the seeder did not create is kept.

    Incidents reference users with no ON DELETE rule on purpose — history should
    outlive an account — so the alternative would be either a failed cleanup or
    deleting somebody's real incident to make room.
    """
    from app import db
    from conftest import incident_payload

    status, created = invoke(
        "POST", "/api/v1/incidents", incident_payload(), token=registered_user["token"]
    )
    assert status == 201
    incident_id = created["incident"]["id"]

    # The account is claimed by the manifest; the incident is not.
    manifest = demo_seed._empty_manifest()
    manifest["users"] = [registered_user["user"]["id"]]
    demo_seed._save_manifest(manifest)

    result = demo_seed.clean()

    assert result["skipped"].get("users") == 1
    assert result["removed"]["users"] == 0
    assert db.query_one(
        "SELECT id FROM users WHERE id = %s", (registered_user["user"]["id"],)
    ) is not None
    assert db.query_one("SELECT id FROM incidents WHERE id = %s", (incident_id,)) is not None

    db.execute("DELETE FROM incidents WHERE id = %s", (incident_id,))


def test_status_reports_absence_cleanly(isolated_manifest):
    assert demo_seed.status() == {"present": False}
