"""Tests for lifecycle timestamps and the timing analytics built on them.

The rule these tests exist to protect: each timestamp records the FIRST time its
event happened and is never rewritten. Without that, reopening a ticket would
silently restate how long the original fix took, and the averages would drift
towards flattering nonsense.

The averages are global, and the suite shares a database, so the timing tests
assert on the exact arithmetic of the change rather than an absolute value:
snapshot the running average and count, add incidents with known durations, and
check the new average is what those numbers must produce.
"""

from conftest import incident_payload

from app import db

ANALYTICS = "/api/v1/admin/analytics"


def _report(invoke, token, **overrides):
    _, body = invoke("POST", "/api/v1/incidents", incident_payload(**overrides), token=token)
    return body["incident"]["id"]


def _patch(invoke, incident_id, changes, token):
    return invoke("PATCH", f"/api/v1/incidents/{incident_id}", changes, token=token)


def _assign(invoke, admin_token, incident_id, assignee_id):
    return _patch(invoke, incident_id, {"assignee_id": assignee_id}, admin_token)


def _stamps(incident_id):
    return db.query_one(
        """
        SELECT created_at, acknowledged_at, assigned_at, resolved_at, closed_at
        FROM incidents WHERE id = %s
        """,
        (incident_id,),
    )


class TestLifecycleTimestamps:
    def test_new_incident_has_only_created_at(self, invoke, registered_user):
        row = _stamps(_report(invoke, registered_user["token"]))

        assert row["created_at"] is not None
        assert row["acknowledged_at"] is None
        assert row["assigned_at"] is None
        assert row["resolved_at"] is None
        assert row["closed_at"] is None

    def test_assignment_sets_assigned_and_acknowledged(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        row = _stamps(iid)
        assert row["assigned_at"] is not None
        # Assigning is itself a staff action, so the ticket is acknowledged.
        assert row["acknowledged_at"] is not None
        assert row["resolved_at"] is None

    def test_status_change_acknowledges_without_assigning(
        self, invoke, registered_user, admin_token
    ):
        """An admin working a ticket directly has acknowledged it but assigned nobody."""
        iid = _report(invoke, registered_user["token"])
        _patch(invoke, iid, {"status": "IN_PROGRESS"}, admin_token)

        row = _stamps(iid)
        assert row["acknowledged_at"] is not None
        assert row["assigned_at"] is None

    def test_resolved_sets_resolved_at(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        _patch(invoke, iid, {"status": "RESOLVED"}, engineer_user["token"])

        row = _stamps(iid)
        assert row["resolved_at"] is not None
        assert row["closed_at"] is None

    def test_closed_sets_closed_at(self, invoke, registered_user, admin_token):
        iid = _report(invoke, registered_user["token"])
        _patch(invoke, iid, {"status": "CLOSED"}, admin_token)

        assert _stamps(iid)["closed_at"] is not None

    def test_unassigning_does_not_clear_assigned_at(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """It really was assigned once; that is a fact about the past."""
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        first = _stamps(iid)["assigned_at"]

        _patch(invoke, iid, {"assignee_id": None}, admin_token)

        assert _stamps(iid)["assigned_at"] == first


class TestTimestampsSurviveReopening:
    def test_reassignment_keeps_the_first_assigned_at(
        self, invoke, registered_user, engineer_user, second_engineer, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        first = _stamps(iid)["assigned_at"]

        _assign(invoke, admin_token, iid, second_engineer["user"]["id"])

        assert _stamps(iid)["assigned_at"] == first

    def test_reopening_keeps_resolved_and_closed(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """Time-to-resolution must describe the original fix, not the rework."""
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        _patch(invoke, iid, {"status": "RESOLVED"}, engineer_user["token"])
        _patch(invoke, iid, {"status": "CLOSED"}, admin_token)
        before = _stamps(iid)

        _patch(invoke, iid, {"status": "OPEN"}, admin_token)
        _patch(invoke, iid, {"status": "RESOLVED"}, admin_token)
        _patch(invoke, iid, {"status": "CLOSED"}, admin_token)

        after = _stamps(iid)
        assert after["resolved_at"] == before["resolved_at"]
        assert after["closed_at"] == before["closed_at"]
        assert after["acknowledged_at"] == before["acknowledged_at"]

    def test_acknowledged_at_is_not_bumped_by_later_edits(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        first = _stamps(iid)["acknowledged_at"]

        _patch(invoke, iid, {"status": "IN_PROGRESS"}, engineer_user["token"])
        _patch(invoke, iid, {"priority": "HIGH"}, admin_token)

        assert _stamps(iid)["acknowledged_at"] == first


class TestTimingAnalytics:
    """Controlled durations written straight to the database, so the expected
    average is arithmetic rather than a guess about how long a test took."""

    def _lifecycle(self, invoke, admin_token):
        _, body = invoke("GET", ANALYTICS, token=admin_token)
        return body["lifecycle"]

    def _with_duration(self, invoke, token, column, seconds):
        """An incident whose `column` sits a known number of seconds after creation."""
        iid = _report(invoke, token)
        db.execute(
            f"UPDATE incidents SET {column} = created_at + make_interval(secs => %s) "
            "WHERE id = %s",
            (seconds, iid),
        )
        return iid

    def test_reports_seconds_and_counts(self, invoke, registered_user, admin_token):
        before = self._lifecycle(invoke, admin_token)

        self._with_duration(invoke, registered_user["token"], "resolved_at", 3600)

        after = self._lifecycle(invoke, admin_token)
        assert after["resolved_count"] == before["resolved_count"] + 1
        assert after["seconds_to_resolve"] is not None

    def test_average_is_exactly_right(self, invoke, registered_user, admin_token):
        before = self._lifecycle(invoke, admin_token)
        count = before["assigned_count"]
        running_total = (before["seconds_to_assign"] or 0) * count

        # 1h and 3h, so the pair contributes a 2h average.
        self._with_duration(invoke, registered_user["token"], "assigned_at", 3600)
        self._with_duration(invoke, registered_user["token"], "assigned_at", 10800)

        after = self._lifecycle(invoke, admin_token)
        expected = (running_total + 3600 + 10800) / (count + 2)

        assert after["assigned_count"] == count + 2
        assert abs(after["seconds_to_assign"] - expected) < 0.01

    def test_unreached_milestones_do_not_drag_the_average(
        self, invoke, registered_user, admin_token
    ):
        """AVG ignores NULLs, so an unresolved incident is absent, not a zero."""
        before = self._lifecycle(invoke, admin_token)

        for _ in range(3):
            _report(invoke, registered_user["token"])

        after = self._lifecycle(invoke, admin_token)
        assert after["resolved_count"] == before["resolved_count"]
        assert after["seconds_to_resolve"] == before["seconds_to_resolve"]

    def test_every_lifecycle_key_is_present(self, invoke, admin_token):
        lifecycle = self._lifecycle(invoke, admin_token)

        for key in (
            "seconds_to_acknowledge", "seconds_to_assign",
            "seconds_to_resolve", "seconds_to_close",
            "acknowledged_count", "assigned_count", "resolved_count", "closed_count",
        ):
            assert key in lifecycle

    def test_employee_cannot_read_timings(self, invoke, registered_user):
        assert invoke("GET", ANALYTICS, token=registered_user["token"])[0] == 403


class TestEngineerAvailability:
    def _availability(self, invoke, token, user_id, value):
        return invoke("PATCH", f"/api/v1/users/{user_id}/availability",
                      {"is_available": value}, token=token)

    def test_engineers_start_available(self, invoke, engineer_user, admin_token):
        _, body = invoke("GET", "/api/v1/engineers", token=admin_token)

        mine = [e for e in body["engineers"] if e["id"] == engineer_user["user"]["id"]]
        assert mine and mine[0]["is_available"] is True

    def test_admin_can_mark_unavailable(self, invoke, engineer_user, admin_token):
        status, body = self._availability(
            invoke, admin_token, engineer_user["user"]["id"], False
        )

        assert status == 200
        assert body["user"]["is_available"] is False

    def test_admin_can_mark_available_again(self, invoke, engineer_user, admin_token):
        self._availability(invoke, admin_token, engineer_user["user"]["id"], False)

        _, body = self._availability(invoke, admin_token, engineer_user["user"]["id"], True)

        assert body["user"]["is_available"] is True

    def test_employee_cannot_manage_availability(
        self, invoke, registered_user, engineer_user
    ):
        """Refused by the route table: employees hold no work, so the setting
        means nothing for them and is not theirs to change for anyone else."""
        assert self._availability(
            invoke, registered_user["token"], engineer_user["user"]["id"], False
        )[0] == 403

    def test_employee_cannot_set_their_own(self, invoke, registered_user):
        assert self._availability(
            invoke, registered_user["token"], registered_user["user"]["id"], False
        )[0] == 403

    def test_engineer_can_manage_their_own_availability(self, invoke, engineer_user):
        """They know first when they are heading out, so they can say so."""
        status, body = self._availability(
            invoke, engineer_user["token"], engineer_user["user"]["id"], False
        )

        assert status == 200
        assert body["user"]["is_available"] is False

    def test_engineer_can_make_themselves_available_again(self, invoke, engineer_user):
        self._availability(invoke, engineer_user["token"], engineer_user["user"]["id"], False)

        _, body = self._availability(
            invoke, engineer_user["token"], engineer_user["user"]["id"], True
        )

        assert body["user"]["is_available"] is True

    def test_engineer_cannot_change_a_colleagues_availability(
        self, invoke, engineer_user, second_engineer
    ):
        """Self-service, not peer management."""
        status, _ = self._availability(
            invoke, engineer_user["token"], second_engineer["user"]["id"], False
        )

        assert status == 403
        assert db.query_one(
            "SELECT is_available FROM users WHERE id = %s",
            (second_engineer["user"]["id"],),
        )["is_available"] is True

    def test_admin_can_still_set_anyone(self, invoke, engineer_user, admin_token):
        status, body = self._availability(
            invoke, admin_token, engineer_user["user"]["id"], False
        )

        assert status == 200
        assert body["user"]["is_available"] is False

    def test_own_availability_is_reported_by_auth_me(self, invoke, engineer_user):
        """The frontend reads its toggle state from here."""
        self._availability(invoke, engineer_user["token"], engineer_user["user"]["id"], False)

        _, body = invoke("GET", "/api/v1/auth/me", token=engineer_user["token"])

        assert body["user"]["is_available"] is False

    def test_unavailable_engineer_still_sees_their_queue(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """Marking yourself out stops new work arriving; it does not sign you out."""
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        self._availability(invoke, engineer_user["token"], engineer_user["user"]["id"], False)

        status, body = invoke("GET", "/api/v1/incidents/assigned", token=engineer_user["token"])
        assert status == 200
        assert iid in [row["id"] for row in body["incidents"]]

    def test_rejected_for_a_non_engineer(self, invoke, registered_user, admin_token):
        status, _ = self._availability(
            invoke, admin_token, registered_user["user"]["id"], False
        )

        assert status == 403

    def test_non_boolean_rejected(self, invoke, engineer_user, admin_token):
        status, body = invoke(
            "PATCH", f"/api/v1/users/{engineer_user['user']['id']}/availability",
            {"is_available": "yes"}, token=admin_token,
        )

        assert status == 400
        assert body["details"]["field"] == "is_available"

    def test_unknown_user(self, invoke, admin_token):
        assert self._availability(invoke, admin_token, 999999, False)[0] == 404

    def test_demotion_resets_availability(self, invoke, engineer_user, admin_token):
        self._availability(invoke, admin_token, engineer_user["user"]["id"], False)

        _, body = invoke("PATCH", f"/api/v1/users/{engineer_user['user']['id']}/role",
                         {"role": "EMPLOYEE"}, token=admin_token)

        assert body["user"]["is_available"] is True


class TestAssignmentRespectsAvailability:
    def _set_available(self, invoke, admin_token, user_id, value):
        return invoke("PATCH", f"/api/v1/users/{user_id}/availability",
                      {"is_available": value}, token=admin_token)

    def test_unavailable_engineer_refuses_new_work(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        self._set_available(invoke, admin_token, engineer_user["user"]["id"], False)
        iid = _report(invoke, registered_user["token"])

        status, body = _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        assert status == 400
        assert body["details"]["field"] == "assignee_id"

    def test_existing_assignment_is_preserved(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """Going on leave must not strip an engineer of work they already hold."""
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        self._set_available(invoke, admin_token, engineer_user["user"]["id"], False)

        # Re-sending the same assignee alongside another change is accepted.
        status, body = _patch(
            invoke, iid,
            {"assignee_id": engineer_user["user"]["id"], "priority": "HIGH"},
            admin_token,
        )

        assert status == 200
        assert body["incident"]["assignee_id"] == engineer_user["user"]["id"]

    def test_unavailable_engineer_keeps_working_their_queue(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        self._set_available(invoke, admin_token, engineer_user["user"]["id"], False)

        assert _patch(invoke, iid, {"status": "IN_PROGRESS"}, engineer_user["token"])[0] == 200

    def test_becoming_available_allows_assignment_again(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        self._set_available(invoke, admin_token, engineer_user["user"]["id"], False)
        iid = _report(invoke, registered_user["token"])
        assert _assign(invoke, admin_token, iid, engineer_user["user"]["id"])[0] == 400

        self._set_available(invoke, admin_token, engineer_user["user"]["id"], True)

        assert _assign(invoke, admin_token, iid, engineer_user["user"]["id"])[0] == 200


class TestEngineerWorkload:
    def _engineer_row(self, invoke, admin_token, engineer_id):
        _, body = invoke("GET", ANALYTICS, token=admin_token)
        for row in body["engineers"]:
            if row["id"] == engineer_id:
                return row
        return None

    def test_engineer_with_no_work_still_appears(
        self, invoke, engineer_user, admin_token
    ):
        """"Who is free?" is answered by the engineers with an empty queue."""
        row = self._engineer_row(invoke, admin_token, engineer_user["user"]["id"])

        assert row is not None
        assert row["active_count"] == 0
        assert row["is_available"] is True

    def test_active_count_rises_with_assignment(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        for _ in range(3):
            iid = _report(invoke, registered_user["token"])
            _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        row = self._engineer_row(invoke, admin_token, engineer_user["user"]["id"])

        assert row["active_count"] == 3
        assert row["total_count"] == 3

    def test_closed_work_is_not_active(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        _patch(invoke, iid, {"status": "CLOSED"}, admin_token)

        row = self._engineer_row(invoke, admin_token, engineer_user["user"]["id"])

        assert row["active_count"] == 0
        assert row["total_count"] == 1

    def test_resolved_work_is_still_active(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        """RESOLVED is awaiting admin review and can be sent back, so it counts."""
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        _patch(invoke, iid, {"status": "RESOLVED"}, engineer_user["token"])

        row = self._engineer_row(invoke, admin_token, engineer_user["user"]["id"])

        assert row["active_count"] == 1

    def test_availability_is_reported(self, invoke, engineer_user, admin_token):
        invoke("PATCH", f"/api/v1/users/{engineer_user['user']['id']}/availability",
               {"is_available": False}, token=admin_token)

        row = self._engineer_row(invoke, admin_token, engineer_user["user"]["id"])

        assert row["is_available"] is False

    def test_workload_is_split_between_engineers(
        self, invoke, registered_user, engineer_user, second_engineer, admin_token
    ):
        for _ in range(2):
            iid = _report(invoke, registered_user["token"])
            _assign(invoke, admin_token, iid, engineer_user["user"]["id"])
        iid = _report(invoke, registered_user["token"])
        _assign(invoke, admin_token, iid, second_engineer["user"]["id"])

        first = self._engineer_row(invoke, admin_token, engineer_user["user"]["id"])
        second = self._engineer_row(invoke, admin_token, second_engineer["user"]["id"])

        assert first["active_count"] == 2
        assert second["active_count"] == 1


class TestAssigneeBreakdown:
    def test_unassigned_is_its_own_bucket(self, invoke, registered_user, admin_token):
        _, before = invoke("GET", ANALYTICS, token=admin_token)
        start = _count_for(before, "Unassigned")

        _report(invoke, registered_user["token"])

        _, after = invoke("GET", ANALYTICS, token=admin_token)
        assert _count_for(after, "Unassigned") == start + 1

    def test_assignment_moves_the_count(
        self, invoke, registered_user, engineer_user, admin_token
    ):
        iid = _report(invoke, registered_user["token"])
        _, before = invoke("GET", ANALYTICS, token=admin_token)

        _assign(invoke, admin_token, iid, engineer_user["user"]["id"])

        _, after = invoke("GET", ANALYTICS, token=admin_token)
        assert _count_for(after, "Unassigned") == _count_for(before, "Unassigned") - 1
        assert _count_for(after, "Engineer Person") == (
            _count_for(before, "Engineer Person") + 1
        )

    def test_reconciles_with_the_total(self, invoke, admin_token):
        _, body = invoke("GET", ANALYTICS, token=admin_token)

        assert sum(row["count"] for row in body["by_assignee"]) == body["total"]


def _count_for(summary, label):
    for row in summary["by_assignee"]:
        if row["label"] == label:
            return row["count"]
    return 0
