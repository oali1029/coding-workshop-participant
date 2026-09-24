"""Tests for the location attached to an incident.

Building and floor are required; a seat is not. The cases that matter most are
the mismatches — a crafted request must not be able to file an incident at
"Building A / Floor 9 of Building B" — and the guarantee that deleting a
facility never destroys incident history.
"""

import uuid

from conftest import incident_payload

from app import db

PREFIX = "pytest-building-"


def _estate(invoke, admin_token, label):
    """Create a fresh building, floor and seat, and return their ids."""
    _, b = invoke(
        "POST",
        "/api/v1/buildings",
        {"name": f"{PREFIX}{label}-{uuid.uuid4().hex[:8]}"},
        token=admin_token,
    )
    building_id = b["building"]["id"]

    _, f = invoke(
        "POST",
        "/api/v1/floors",
        {"building_id": building_id, "name": "Floor 1"},
        token=admin_token,
    )
    floor_id = f["floor"]["id"]

    _, s = invoke(
        "POST", "/api/v1/seats", {"floor_id": floor_id, "code": "A-101"}, token=admin_token
    )

    return {"building_id": building_id, "floor_id": floor_id, "seat_id": s["seat"]["id"]}


class TestRequiredLocation:
    def test_building_and_floor_only(self, invoke, registered_user, facility):
        """Lifts, bathrooms and plant rooms have no seat."""
        status, body = invoke(
            "POST",
            "/api/v1/incidents",
            incident_payload(title="East elevator is stuck"),
            token=registered_user["token"],
        )

        assert status == 201
        assert body["incident"]["building_id"] == facility["building_id"]
        assert body["incident"]["floor_id"] == facility["floor_id"]
        assert body["incident"]["seat_id"] is None

    def test_with_seat(self, invoke, registered_user, facility):
        _, body = invoke(
            "POST",
            "/api/v1/incidents",
            incident_payload(seat_id=facility["seat_id"]),
            token=registered_user["token"],
        )

        assert body["incident"]["seat_id"] == facility["seat_id"]
        assert body["incident"]["seat_code"] == "T-001"

    def test_missing_building(self, invoke, registered_user):
        payload = incident_payload()
        del payload["building_id"]

        status, body = invoke("POST", "/api/v1/incidents", payload, token=registered_user["token"])

        assert status == 400
        assert body["details"]["field"] == "building_id"

    def test_missing_floor(self, invoke, registered_user):
        payload = incident_payload()
        del payload["floor_id"]

        status, body = invoke("POST", "/api/v1/incidents", payload, token=registered_user["token"])

        assert status == 400
        assert body["details"]["field"] == "floor_id"

    def test_returns_names(self, invoke, registered_user):
        _, body = invoke(
            "POST", "/api/v1/incidents", incident_payload(), token=registered_user["token"]
        )

        assert body["incident"]["building_name"].startswith(PREFIX)
        assert body["incident"]["floor_name"] == "Floor 1"


class TestMismatchRejected:
    """The frontend cascades, but the API must not trust that it did."""

    def test_floor_from_other_building(self, invoke, registered_user, admin_token, facility):
        other = _estate(invoke, admin_token, "other")

        status, body = invoke(
            "POST",
            "/api/v1/incidents",
            incident_payload(building_id=facility["building_id"], floor_id=other["floor_id"]),
            token=registered_user["token"],
        )

        assert status == 400
        assert body["details"]["field"] == "floor_id"

    def test_seat_from_other_floor(self, invoke, registered_user, admin_token, facility):
        other = _estate(invoke, admin_token, "otherseat")

        status, body = invoke(
            "POST",
            "/api/v1/incidents",
            incident_payload(seat_id=other["seat_id"]),
            token=registered_user["token"],
        )

        assert status == 400
        assert body["details"]["field"] == "seat_id"

    def test_unknown_building(self, invoke, registered_user):
        status, _ = invoke(
            "POST",
            "/api/v1/incidents",
            incident_payload(building_id=999999),
            token=registered_user["token"],
        )

        assert status == 400

    def test_unknown_floor(self, invoke, registered_user):
        status, _ = invoke(
            "POST",
            "/api/v1/incidents",
            incident_payload(floor_id=999999),
            token=registered_user["token"],
        )

        assert status == 400

    def test_unknown_seat(self, invoke, registered_user):
        status, _ = invoke(
            "POST",
            "/api/v1/incidents",
            incident_payload(seat_id=999999),
            token=registered_user["token"],
        )

        assert status == 400

    def test_nothing_stored_on_reject(self, invoke, registered_user):
        status, _ = invoke(
            "POST",
            "/api/v1/incidents",
            incident_payload(title="Should not exist", floor_id=999999),
            token=registered_user["token"],
        )

        assert status == 400
        assert (
            db.query_one("SELECT id FROM incidents WHERE title = %s", ("Should not exist",))
            is None
        )


class TestFreeText:
    def test_details_kept_with_structure(self, invoke, registered_user):
        _, body = invoke(
            "POST",
            "/api/v1/incidents",
            incident_payload(location="Men's restroom sink is leaking"),
            token=registered_user["token"],
        )

        assert body["incident"]["location"] == "Men's restroom sink is leaking"
        assert body["incident"]["building_id"] is not None

    def test_details_optional(self, invoke, registered_user):
        _, body = invoke(
            "POST", "/api/v1/incidents", incident_payload(), token=registered_user["token"]
        )

        assert body["incident"]["location"] is None


class TestHistoricalSafety:
    def test_snapshot_written(self, invoke, registered_user, facility):
        _, body = invoke(
            "POST",
            "/api/v1/incidents",
            incident_payload(seat_id=facility["seat_id"]),
            token=registered_user["token"],
        )

        assert body["incident"]["location_snapshot"].endswith("> Floor 1 > T-001")

    def test_snapshot_without_seat(self, invoke, registered_user):
        _, body = invoke(
            "POST", "/api/v1/incidents", incident_payload(), token=registered_user["token"]
        )

        assert body["incident"]["location_snapshot"].endswith("> Floor 1")

    def test_delete_building_keeps_incident(self, invoke, registered_user, admin_token):
        """The whole point of the snapshot: history must survive a demolition."""
        estate = _estate(invoke, admin_token, "doomed")

        _, made = invoke(
            "POST",
            "/api/v1/incidents",
            incident_payload(
                title="Reported before demolition",
                building_id=estate["building_id"],
                floor_id=estate["floor_id"],
                seat_id=estate["seat_id"],
            ),
            token=registered_user["token"],
        )
        incident_id = made["incident"]["id"]
        snapshot = made["incident"]["location_snapshot"]

        status, deleted = invoke(
            "DELETE", f"/api/v1/buildings/{estate['building_id']}", token=admin_token
        )
        assert status == 200
        assert deleted["incidents_detached"] == 1

        _, body = invoke(
            "GET", f"/api/v1/incidents/{incident_id}", token=registered_user["token"]
        )

        # The incident survives, its references are gone, the snapshot remains.
        assert body["incident"]["title"] == "Reported before demolition"
        assert body["incident"]["building_id"] is None
        assert body["incident"]["floor_id"] is None
        assert body["incident"]["seat_id"] is None
        assert body["incident"]["location_snapshot"] == snapshot

    def test_delete_seat_keeps_floor(self, invoke, registered_user, admin_token):
        estate = _estate(invoke, admin_token, "seatgone")

        _, made = invoke(
            "POST",
            "/api/v1/incidents",
            incident_payload(
                building_id=estate["building_id"],
                floor_id=estate["floor_id"],
                seat_id=estate["seat_id"],
            ),
            token=registered_user["token"],
        )

        invoke("DELETE", f"/api/v1/seats/{estate['seat_id']}", token=admin_token)

        _, body = invoke(
            "GET", f"/api/v1/incidents/{made['incident']['id']}", token=registered_user["token"]
        )

        assert body["incident"]["seat_id"] is None
        assert body["incident"]["building_id"] == estate["building_id"]
        assert body["incident"]["floor_id"] == estate["floor_id"]

    def test_legacy_incident_keeps_text(self, invoke, registered_user):
        """Slices 2-4 incidents have no structured location and must still work.

        Inserted directly, because the API now requires a building and floor —
        which is exactly the shape of a pre-migration row.
        """
        row = db.query_one(
            """
            INSERT INTO incidents (title, description, category, priority, status,
                                   location, created_by)
            VALUES (%s, %s, 'OTHER', 'MEDIUM', 'OPEN', %s, %s)
            RETURNING id
            """,
            (
                "Legacy incident",
                "Reported before facilities existed.",
                "Building A, 3rd floor",
                registered_user["user"]["id"],
            ),
        )

        status, body = invoke(
            "GET", f"/api/v1/incidents/{row['id']}", token=registered_user["token"]
        )

        assert status == 200
        assert body["incident"]["location"] == "Building A, 3rd floor"
        assert body["incident"]["building_id"] is None
        assert body["incident"]["location_snapshot"] is None


class TestLocationInLists:
    def test_my_incidents(self, invoke, registered_user):
        invoke("POST", "/api/v1/incidents", incident_payload(), token=registered_user["token"])

        _, body = invoke("GET", "/api/v1/incidents", token=registered_user["token"])

        assert body["incidents"][0]["building_name"].startswith(PREFIX)

    def test_admin_list(self, invoke, registered_user, admin_token):
        invoke("POST", "/api/v1/incidents", incident_payload(), token=registered_user["token"])

        _, body = invoke("GET", "/api/v1/admin/incidents", token=admin_token)

        assert body["incidents"][0]["building_name"] is not None

    def test_assigned_queue(self, invoke, registered_user, engineer_user, admin_token):
        _, made = invoke(
            "POST", "/api/v1/incidents", incident_payload(), token=registered_user["token"]
        )
        invoke(
            "PATCH",
            f"/api/v1/incidents/{made['incident']['id']}",
            {"assignee_id": engineer_user["user"]["id"]},
            token=admin_token,
        )

        _, body = invoke("GET", "/api/v1/incidents/assigned", token=engineer_user["token"])

        assert body["incidents"][0]["building_name"] is not None
