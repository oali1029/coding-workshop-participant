"""Tests for recurring-problem detection and estimated operational impact.

The rule worth protecting: three people reporting one broken lift are three
incidents and ONE problem. Every incident count elsewhere must still say three,
and the impact estimate must charge for it once.

Durations are written straight to the database so the expected figure is
arithmetic rather than a guess about how long a test took.

The money tests assert on a single problem's own estimated_impact rather than on
a change in the running total. The total includes active problems elsewhere in
this shared database, and those grow by the second — diffing it could only ever
be approximate, and exactness is the whole point here.
"""

import uuid

from conftest import TEST_BUILDING_PREFIX, incident_payload

from app import db
from app.domains.analytics import PRIORITY_HOURLY_RATES, RECURRING_THRESHOLD
from app.domains.incidents import PRIORITIES

ANALYTICS = "/api/v1/admin/analytics"


def _insights(invoke, admin_token):
    status, body = invoke("GET", ANALYTICS, token=admin_token)
    assert status == 200
    return body["operational"]


def _place():
    """A building and floor of this suite's own, so its groups start empty."""
    name = f"{TEST_BUILDING_PREFIX}{uuid.uuid4().hex[:8]}"
    building = db.query_one(
        "INSERT INTO buildings (name) VALUES (%s) RETURNING id", (name,)
    )
    floor = db.query_one(
        "INSERT INTO floors (building_id, name) VALUES (%s, %s) RETURNING id",
        (building["id"], "Floor 1"),
    )
    return {"name": name, "building_id": building["id"], "floor_id": floor["id"]}


def _seat(floor_id, code):
    return db.query_one(
        "INSERT INTO seats (floor_id, code) VALUES (%s, %s) RETURNING id",
        (floor_id, code),
    )["id"]


def _report(invoke, token, place, **overrides):
    payload = incident_payload(
        building_id=place["building_id"], floor_id=place["floor_id"], **overrides
    )
    _, body = invoke("POST", "/api/v1/incidents", payload, token=token)
    return body["incident"]["id"]


def _age(incident_id, hours_ago):
    """Backdate a report so a known number of hours have elapsed since it."""
    db.execute(
        "UPDATE incidents SET created_at = now() - make_interval(hours => %s) WHERE id = %s",
        (hours_ago, incident_id),
    )


def _resolve_after(incident_id, hours_after_creation):
    """Mark an incident resolved a known number of hours after it was reported."""
    db.execute(
        """
        UPDATE incidents
        SET status = 'RESOLVED',
            resolved_at = created_at + make_interval(hours => %s)
        WHERE id = %s
        """,
        (hours_after_creation, incident_id),
    )


def _find(insights, location, category):
    for row in insights["recurring_problems"]:
        if row["location"] == location and row["category"] == category:
            return row
    return None


class TestRecurringDetection:
    def test_three_reports_are_recurring(self, invoke, registered_user, admin_token):
        place = _place()
        for _ in range(RECURRING_THRESHOLD):
            _report(invoke, registered_user["token"], place, category="TECHNOLOGY")

        found = _find(_insights(invoke, admin_token), f"{place['name']} > Floor 1",
                      "TECHNOLOGY")

        assert found is not None
        assert found["reports"] == 3

    def test_two_reports_are_not(self, invoke, registered_user, admin_token):
        place = _place()
        for _ in range(2):
            _report(invoke, registered_user["token"], place, category="TECHNOLOGY")

        assert _find(_insights(invoke, admin_token), f"{place['name']} > Floor 1",
                     "TECHNOLOGY") is None

    def test_different_categories_do_not_combine(
        self, invoke, registered_user, admin_token
    ):
        """Two faults in one place are two problems, not one recurring one."""
        place = _place()
        for _ in range(2):
            _report(invoke, registered_user["token"], place, category="TECHNOLOGY")
        _report(invoke, registered_user["token"], place, category="PLUMBING")

        insights = _insights(invoke, admin_token)

        assert _find(insights, f"{place['name']} > Floor 1", "TECHNOLOGY") is None
        assert _find(insights, f"{place['name']} > Floor 1", "PLUMBING") is None

    def test_different_seats_do_not_combine(self, invoke, registered_user, admin_token):
        place = _place()
        first = _seat(place["floor_id"], "A-1")
        second = _seat(place["floor_id"], "A-2")
        for _ in range(2):
            _report(invoke, registered_user["token"], place, seat_id=first,
                    category="TECHNOLOGY")
        _report(invoke, registered_user["token"], place, seat_id=second,
                category="TECHNOLOGY")

        insights = _insights(invoke, admin_token)

        assert _find(insights, f"{place['name']} > Floor 1 > A-1", "TECHNOLOGY") is None

    def test_same_seat_groups_and_labels_fully(
        self, invoke, registered_user, admin_token
    ):
        place = _place()
        seat = _seat(place["floor_id"], "A-312")
        for _ in range(3):
            _report(invoke, registered_user["token"], place, seat_id=seat,
                    category="TECHNOLOGY")

        found = _find(_insights(invoke, admin_token),
                      f"{place['name']} > Floor 1 > A-312", "TECHNOLOGY")

        assert found is not None
        assert found["reports"] == 3

    def test_seatless_reports_group_on_building_and_floor(
        self, invoke, registered_user, admin_token
    ):
        """A lift or a corridor has no seat; those reports still group."""
        place = _place()
        for _ in range(3):
            _report(invoke, registered_user["token"], place, category="ELECTRICAL")

        found = _find(_insights(invoke, admin_token), f"{place['name']} > Floor 1",
                      "ELECTRICAL")

        assert found is not None
        assert found["reports"] == 3

    def test_a_seated_report_does_not_join_the_seatless_group(
        self, invoke, registered_user, admin_token
    ):
        place = _place()
        seat = _seat(place["floor_id"], "B-1")
        for _ in range(2):
            _report(invoke, registered_user["token"], place, category="FURNITURE")
        _report(invoke, registered_user["token"], place, seat_id=seat,
                category="FURNITURE")

        assert _find(_insights(invoke, admin_token), f"{place['name']} > Floor 1",
                     "FURNITURE") is None

    def test_reports_outside_the_window_do_not_count(
        self, invoke, registered_user, admin_token
    ):
        place = _place()
        old = _report(invoke, registered_user["token"], place, category="HVAC")
        _age(old, 24 * 31)
        for _ in range(2):
            _report(invoke, registered_user["token"], place, category="HVAC")

        assert _find(_insights(invoke, admin_token), f"{place['name']} > Floor 1",
                     "HVAC") is None

    def test_sorted_by_report_count(self, invoke, registered_user, admin_token):
        counts = [
            row["reports"] for row in _insights(invoke, admin_token)["recurring_problems"]
        ]

        assert counts == sorted(counts, reverse=True)

    def test_employee_and_engineer_refused(
        self, invoke, registered_user, engineer_user
    ):
        assert invoke("GET", ANALYTICS, token=registered_user["token"])[0] == 403
        assert invoke("GET", ANALYTICS, token=engineer_user["token"])[0] == 403


class TestPriorityRates:
    def test_rates_are_exactly_the_agreed_figures(self):
        assert PRIORITY_HOURLY_RATES == {"LOW": 10, "MEDIUM": 25, "HIGH": 50}

    def test_no_priority_is_invented_or_missing(self):
        """Guards against a CRITICAL tier creeping in through the rate table."""
        assert set(PRIORITY_HOURLY_RATES) == set(PRIORITIES)
        assert set(PRIORITIES) == {"LOW", "MEDIUM", "HIGH"}

    def test_api_never_reports_an_unknown_priority(self, invoke, admin_token):
        insights = _insights(invoke, admin_token)

        assert set(insights["impact_by_priority"]) == {"LOW", "MEDIUM", "HIGH"}
        assert insights["hourly_rates"] == {"LOW": 10, "MEDIUM": 25, "HIGH": 50}

    def test_critical_is_rejected_by_the_api(self, invoke, registered_user):
        place = _place()
        payload = incident_payload(
            building_id=place["building_id"], floor_id=place["floor_id"],
            priority="CRITICAL",
        )

        status, _ = invoke("POST", "/api/v1/incidents", payload,
                           token=registered_user["token"])

        assert status == 400


class TestEstimatedImpact:
    """These assert a single problem's own figure rather than a change in the
    running total. The total includes active problems elsewhere in the shared
    database, which grow by the second — diffing it can only ever be approximate,
    and the point of these tests is exactness."""

    def _resolved_problem(self, invoke, token, admin_token, *, reports, priority, hours):
        """A group of duplicate reports, resolved a known number of hours later.

        Uses the recurring threshold so the group appears in the response with
        its own estimated_impact.
        """
        place = _place()

        for _ in range(reports):
            incident = _report(invoke, token, place, category="TECHNOLOGY",
                               priority=priority)
            _age(incident, hours)
            _resolve_after(incident, hours)

        found = _find(_insights(invoke, admin_token), f"{place['name']} > Floor 1",
                      "TECHNOLOGY")
        assert found is not None, "the group should have reached the recurring threshold"
        return found

    def test_low_rate(self, invoke, registered_user, admin_token):
        found = self._resolved_problem(
            invoke, registered_user["token"], admin_token,
            reports=RECURRING_THRESHOLD, priority="LOW", hours=10,
        )

        assert found["estimated_impact"] == 100.0

    def test_medium_rate(self, invoke, registered_user, admin_token):
        found = self._resolved_problem(
            invoke, registered_user["token"], admin_token,
            reports=RECURRING_THRESHOLD, priority="MEDIUM", hours=10,
        )

        assert found["estimated_impact"] == 250.0

    def test_high_rate(self, invoke, registered_user, admin_token):
        found = self._resolved_problem(
            invoke, registered_user["token"], admin_token,
            reports=RECURRING_THRESHOLD, priority="HIGH", hours=10,
        )

        assert found["estimated_impact"] == 500.0

    def test_duplicate_reports_do_not_multiply_the_estimate(
        self, invoke, registered_user, admin_token
    ):
        """The worked example: 3 HIGH reports, 6 hours, $300 — not $900."""
        found = self._resolved_problem(
            invoke, registered_user["token"], admin_token,
            reports=3, priority="HIGH", hours=6,
        )

        assert found["reports"] == 3, "all three reports are still counted as reports"
        assert found["estimated_impact"] == 300.0
        assert found["estimated_impact"] != 900.0

    def test_more_duplicates_do_not_raise_the_figure(
        self, invoke, registered_user, admin_token
    ):
        """Six reports of one problem cost the same as three."""
        three = self._resolved_problem(
            invoke, registered_user["token"], admin_token,
            reports=3, priority="HIGH", hours=6,
        )
        six = self._resolved_problem(
            invoke, registered_user["token"], admin_token,
            reports=6, priority="HIGH", hours=6,
        )

        assert six["reports"] == 6
        assert six["estimated_impact"] == three["estimated_impact"] == 300.0

    def test_unrelated_problems_are_counted_separately(
        self, invoke, registered_user, admin_token
    ):
        first = self._resolved_problem(
            invoke, registered_user["token"], admin_token,
            reports=3, priority="HIGH", hours=2,
        )
        second = self._resolved_problem(
            invoke, registered_user["token"], admin_token,
            reports=3, priority="HIGH", hours=2,
        )

        # Two separate problems at 2h x $50 each, charged individually.
        assert first["estimated_impact"] == 100.0
        assert second["estimated_impact"] == 100.0
        assert first["location"] != second["location"]

    def test_problem_count_is_groups_not_reports(
        self, invoke, registered_user, admin_token
    ):
        before = _insights(invoke, admin_token)
        place = _place()
        for _ in range(3):
            _report(invoke, registered_user["token"], place, category="TECHNOLOGY")

        after = _insights(invoke, admin_token)

        assert after["problem_count"] == before["problem_count"] + 1


class TestMixedPriorities:
    def test_group_takes_the_highest_priority(
        self, invoke, registered_user, admin_token
    ):
        """LOW + MEDIUM + HIGH in one place is charged at the HIGH rate."""
        place = _place()

        for priority in ("LOW", "MEDIUM", "HIGH"):
            incident = _report(invoke, registered_user["token"], place,
                               category="TECHNOLOGY", priority=priority)
            _age(incident, 4)
            _resolve_after(incident, 4)

        found = _find(_insights(invoke, admin_token), f"{place['name']} > Floor 1",
                      "TECHNOLOGY")

        # One problem, 4 hours, charged at the HIGH rate rather than the lowest
        # or an average of the three.
        assert found["priority"] == "HIGH"
        assert found["estimated_impact"] == 200.0

    def test_charged_to_the_highest_priority_bucket(
        self, invoke, registered_user, admin_token
    ):
        """A mixed group contributes wholly to HIGH, nothing to LOW."""
        before = _insights(invoke, admin_token)
        place = _place()

        for priority in ("LOW", "LOW", "HIGH"):
            incident = _report(invoke, registered_user["token"], place,
                               category="PLUMBING", priority=priority)
            _age(incident, 4)
            _resolve_after(incident, 4)

        after = _insights(invoke, admin_token)
        found = _find(after, f"{place['name']} > Floor 1", "PLUMBING")

        assert found["estimated_impact"] == 200.0
        assert after["impact_by_priority"]["HIGH"] == round(
            before["impact_by_priority"]["HIGH"] + 200.0, 2
        )
        # LOW is untouched: the group was charged at HIGH, not split.
        assert after["impact_by_priority"]["LOW"] == before["impact_by_priority"]["LOW"]


class TestDuration:
    def test_earliest_report_starts_the_clock(
        self, invoke, registered_user, admin_token
    ):
        """The problem began when the first person hit it, not the last."""
        place = _place()

        ids = [
            _report(invoke, registered_user["token"], place,
                    category="TECHNOLOGY", priority="LOW")
            for _ in range(3)
        ]
        # Reported 10, 6 and 2 hours ago, all fixed at the same moment now.
        for incident, hours_ago in zip(ids, (10, 6, 2)):
            _age(incident, hours_ago)
        db.execute(
            "UPDATE incidents SET status = 'RESOLVED', resolved_at = now() "
            "WHERE id = ANY(%s)",
            (ids,),
        )

        found = _find(_insights(invoke, admin_token), f"{place['name']} > Floor 1",
                      "TECHNOLOGY")

        # 10 hours from the earliest report, not 2 from the latest.
        assert found["estimated_impact"] == 100.0

    def test_resolved_problem_stops_accumulating(
        self, invoke, registered_user, admin_token
    ):
        place = _place()
        incident = _report(invoke, registered_user["token"], place,
                           category="TECHNOLOGY", priority="LOW")
        _age(incident, 20)
        _resolve_after(incident, 5)

        first = _insights(invoke, admin_token)["estimated_impact"]
        second = _insights(invoke, admin_token)["estimated_impact"]

        # Reported 20h ago but fixed after 5h, so it is charged 5h and stays there.
        assert first == second

    def test_active_problem_runs_to_now(self, invoke, registered_user, admin_token):
        before = _insights(invoke, admin_token)
        place = _place()
        incident = _report(invoke, registered_user["token"], place,
                           category="TECHNOLOGY", priority="LOW")
        _age(incident, 8)

        after = _insights(invoke, admin_token)
        delta = after["estimated_impact"] - before["estimated_impact"]

        # 8 hours at $10, give or take the moment the query ran.
        assert 79.0 < delta < 81.0

    def test_active_problem_counts_towards_active_impact(
        self, invoke, registered_user, admin_token
    ):
        before = _insights(invoke, admin_token)
        place = _place()
        incident = _report(invoke, registered_user["token"], place,
                           category="TECHNOLOGY", priority="LOW")
        _age(incident, 8)

        after = _insights(invoke, admin_token)

        assert after["active_impact"] > before["active_impact"]

    def test_resolved_problem_leaves_active_impact_alone(
        self, invoke, registered_user, admin_token
    ):
        """A fixed problem still counts towards the estimate, but not the active
        figure — that card answers "what is costing us right now?".

        Asserted against the problem's own row and a bound on the active total,
        because other active problems in this shared database grow by the second
        and an equality on that total could never hold.
        """
        before = _insights(invoke, admin_token)
        place = _place()

        for _ in range(3):
            incident = _report(invoke, registered_user["token"], place,
                               category="TECHNOLOGY", priority="HIGH")
            _age(incident, 8)
            _resolve_after(incident, 8)

        after = _insights(invoke, admin_token)
        found = _find(after, f"{place['name']} > Floor 1", "TECHNOLOGY")

        assert found["is_active"] is False
        assert found["estimated_impact"] == 400.0
        # Its $400 is in the estimate but nowhere near the active figure, which
        # has only drifted by the seconds that elapsed between the two reads.
        assert after["active_impact"] - before["active_impact"] < 1.0

    def test_one_unresolved_report_keeps_the_problem_active(
        self, invoke, registered_user, admin_token
    ):
        """The problem is only over once the last ticket for it is."""
        place = _place()
        fixed = _report(invoke, registered_user["token"], place, category="HVAC")
        _report(invoke, registered_user["token"], place, category="HVAC")
        _report(invoke, registered_user["token"], place, category="HVAC")
        _resolve_after(fixed, 1)

        found = _find(_insights(invoke, admin_token), f"{place['name']} > Floor 1", "HVAC")

        assert found["is_active"] is True


class TestReconciliation:
    def test_priority_totals_sum_to_the_estimate(self, invoke, admin_token):
        insights = _insights(invoke, admin_token)

        assert round(sum(insights["impact_by_priority"].values()), 2) == (
            insights["estimated_impact"]
        )

    def test_active_impact_never_exceeds_the_estimate(self, invoke, admin_token):
        insights = _insights(invoke, admin_token)

        assert insights["active_impact"] <= insights["estimated_impact"]

    def test_recurring_count_matches_the_list(self, invoke, admin_token):
        insights = _insights(invoke, admin_token)

        assert insights["recurring_count"] == len(insights["recurring_problems"])

    def test_every_listed_problem_meets_the_threshold(self, invoke, admin_token):
        insights = _insights(invoke, admin_token)

        assert all(
            row["reports"] >= RECURRING_THRESHOLD
            for row in insights["recurring_problems"]
        )


class TestOrdinaryCountsAreUnchanged:
    def test_three_duplicate_reports_are_still_three_incidents(
        self, invoke, registered_user, admin_token
    ):
        """The headline counts are per incident and must not be deduplicated."""
        _, before = invoke("GET", ANALYTICS, token=admin_token)
        place = _place()
        for _ in range(3):
            _report(invoke, registered_user["token"], place, category="TECHNOLOGY")

        _, after = invoke("GET", ANALYTICS, token=admin_token)

        assert after["total"] == before["total"] + 3
        assert after["by_status"]["OPEN"] == before["by_status"]["OPEN"] + 3
        assert after["by_category"]["TECHNOLOGY"] == before["by_category"]["TECHNOLOGY"] + 3
        # ...while the same three reports are one underlying problem.
        assert after["operational"]["problem_count"] == (
            before["operational"]["problem_count"] + 1
        )

    def test_duplicates_still_appear_individually_in_the_admin_list(
        self, invoke, registered_user, admin_token
    ):
        place = _place()
        tag = f"dup{uuid.uuid4().hex[:8]}"
        for _ in range(3):
            _report(invoke, registered_user["token"], place, title=f"Lift {tag}")

        _, body = invoke("GET", "/api/v1/admin/incidents", token=admin_token,
                         query={"q": tag})

        assert len(body["incidents"]) == 3

    def test_building_breakdown_still_counts_every_report(
        self, invoke, registered_user, admin_token
    ):
        place = _place()
        for _ in range(3):
            _report(invoke, registered_user["token"], place)

        _, body = invoke("GET", ANALYTICS, token=admin_token)
        counts = {row["label"]: row["count"] for row in body["by_building"]}

        assert counts[place["name"]] == 3
