"""Tests for the Building > Floor > Seat hierarchy.

The rules worth guarding are: only admins may change the estate, names are
unique per parent rather than globally, and deleting a building takes its floors
and seats with it. 
"""

import uuid

from app import db

PREFIX = "pytest-building-"


def _name(label):
    """A building name unique to this test, so the suite can run repeatedly."""
    return f"{PREFIX}{label}-{uuid.uuid4().hex[:8]}"


def _building(invoke, admin_token, label="b"):
    _, body = invoke("POST", "/api/v1/buildings", {"name": _name(label)}, token=admin_token)
    return body["building"]["id"]


def _floor(invoke, admin_token, building_id, name="Floor 1"):
    _, body = invoke(
        "POST", "/api/v1/floors", {"building_id": building_id, "name": name}, token=admin_token
    )
    return body["floor"]["id"]


def _seat(invoke, admin_token, floor_id, code="A-101"):
    _, body = invoke(
        "POST", "/api/v1/seats", {"floor_id": floor_id, "code": code}, token=admin_token
    )
    return body["seat"]["id"]


class TestBuildings:
    def test_create_and_list(self, invoke, admin_token):
        name = _name("create")
        status, body = invoke(
            "POST", "/api/v1/buildings", {"name": name, "address": "1 Main St"}, token=admin_token
        )

        assert status == 201
        assert body["building"]["name"] == name
        assert body["building"]["address"] == "1 Main St"

        _, listing = invoke("GET", "/api/v1/buildings", token=admin_token)
        assert name in [b["name"] for b in listing["buildings"]]

    def test_address_optional(self, invoke, admin_token):
        _, body = invoke("POST", "/api/v1/buildings", {"name": _name("noaddr")}, token=admin_token)

        assert body["building"]["address"] is None

    def test_duplicate_name(self, invoke, admin_token):
        name = _name("dup")
        invoke("POST", "/api/v1/buildings", {"name": name}, token=admin_token)

        status, body = invoke("POST", "/api/v1/buildings", {"name": name}, token=admin_token)

        assert status == 409
        assert body["error"] == "conflict"

    def test_missing_name(self, invoke, admin_token):
        status, body = invoke("POST", "/api/v1/buildings", {}, token=admin_token)

        assert status == 400
        assert body["details"]["field"] == "name"

    def test_rename(self, invoke, admin_token):
        building_id = _building(invoke, admin_token)
        new_name = _name("renamed")

        status, body = invoke(
            "PATCH", f"/api/v1/buildings/{building_id}", {"name": new_name}, token=admin_token
        )

        assert status == 200
        assert body["building"]["name"] == new_name

    def test_delete(self, invoke, admin_token):
        building_id = _building(invoke, admin_token)

        status, body = invoke("DELETE", f"/api/v1/buildings/{building_id}", token=admin_token)

        assert status == 200
        assert body["deleted"] == building_id
        assert db.query_one("SELECT id FROM buildings WHERE id = %s", (building_id,)) is None

    def test_unknown_id(self, invoke, admin_token):
        status, _ = invoke("DELETE", "/api/v1/buildings/999999", token=admin_token)

        assert status == 404

    def test_non_numeric_id(self, invoke, admin_token):
        status, _ = invoke("GET", "/api/v1/buildings/abc/floors", token=admin_token)

        assert status == 404


class TestFloors:
    def test_create_and_list(self, invoke, admin_token):
        building_id = _building(invoke, admin_token)

        status, body = invoke(
            "POST",
            "/api/v1/floors",
            {"building_id": building_id, "name": "Floor 3"},
            token=admin_token,
        )
        assert status == 201
        assert body["floor"]["building_id"] == building_id

        _, listing = invoke("GET", f"/api/v1/buildings/{building_id}/floors", token=admin_token)
        assert [f["name"] for f in listing["floors"]] == ["Floor 3"]

    def test_same_name_other_building(self, invoke, admin_token):
        """Uniqueness is per building — every building has a "Floor 3"."""
        first = _building(invoke, admin_token, "first")
        second = _building(invoke, admin_token, "second")

        _floor(invoke, admin_token, first, "Floor 3")
        status, _ = invoke(
            "POST", "/api/v1/floors", {"building_id": second, "name": "Floor 3"}, token=admin_token
        )

        assert status == 201

    def test_duplicate_in_same_building(self, invoke, admin_token):
        building_id = _building(invoke, admin_token)
        _floor(invoke, admin_token, building_id, "Floor 3")

        status, body = invoke(
            "POST",
            "/api/v1/floors",
            {"building_id": building_id, "name": "Floor 3"},
            token=admin_token,
        )

        assert status == 409
        assert body["error"] == "conflict"

    def test_unknown_building(self, invoke, admin_token):
        status, body = invoke(
            "POST", "/api/v1/floors", {"building_id": 999999, "name": "Floor 1"}, token=admin_token
        )

        assert status == 400
        assert body["details"]["field"] == "building_id"

    def test_rename_and_delete(self, invoke, admin_token):
        building_id = _building(invoke, admin_token)
        floor_id = _floor(invoke, admin_token, building_id)

        status, body = invoke(
            "PATCH", f"/api/v1/floors/{floor_id}", {"name": "Ground"}, token=admin_token
        )
        assert status == 200
        assert body["floor"]["name"] == "Ground"

        status, _ = invoke("DELETE", f"/api/v1/floors/{floor_id}", token=admin_token)
        assert status == 200
        assert db.query_one("SELECT id FROM floors WHERE id = %s", (floor_id,)) is None


class TestSeats:
    def test_create_and_list(self, invoke, admin_token):
        building_id = _building(invoke, admin_token)
        floor_id = _floor(invoke, admin_token, building_id)

        status, body = invoke(
            "POST", "/api/v1/seats", {"floor_id": floor_id, "code": "A-312"}, token=admin_token
        )
        assert status == 201
        assert body["seat"]["code"] == "A-312"

        _, listing = invoke("GET", f"/api/v1/floors/{floor_id}/seats", token=admin_token)
        assert [s["code"] for s in listing["seats"]] == ["A-312"]

    def test_duplicate_code(self, invoke, admin_token):
        building_id = _building(invoke, admin_token)
        floor_id = _floor(invoke, admin_token, building_id)
        _seat(invoke, admin_token, floor_id, "A-312")

        status, _ = invoke(
            "POST", "/api/v1/seats", {"floor_id": floor_id, "code": "A-312"}, token=admin_token
        )

        assert status == 409

    def test_unknown_floor(self, invoke, admin_token):
        status, body = invoke(
            "POST", "/api/v1/seats", {"floor_id": 999999, "code": "A-1"}, token=admin_token
        )

        assert status == 400
        assert body["details"]["field"] == "floor_id"

    def test_rename_and_delete(self, invoke, admin_token):
        building_id = _building(invoke, admin_token)
        floor_id = _floor(invoke, admin_token, building_id)
        seat_id = _seat(invoke, admin_token, floor_id)

        status, body = invoke(
            "PATCH", f"/api/v1/seats/{seat_id}", {"code": "B-200"}, token=admin_token
        )
        assert status == 200
        assert body["seat"]["code"] == "B-200"

        status, _ = invoke("DELETE", f"/api/v1/seats/{seat_id}", token=admin_token)
        assert status == 200


class TestHierarchyCascade:
    def test_building_cascades(self, invoke, admin_token):
        building_id = _building(invoke, admin_token)
        floor_id = _floor(invoke, admin_token, building_id)
        seat_id = _seat(invoke, admin_token, floor_id)

        invoke("DELETE", f"/api/v1/buildings/{building_id}", token=admin_token)

        assert db.query_one("SELECT id FROM floors WHERE id = %s", (floor_id,)) is None
        assert db.query_one("SELECT id FROM seats WHERE id = %s", (seat_id,)) is None

    def test_floor_cascades(self, invoke, admin_token):
        building_id = _building(invoke, admin_token)
        floor_id = _floor(invoke, admin_token, building_id)
        seat_id = _seat(invoke, admin_token, floor_id)

        invoke("DELETE", f"/api/v1/floors/{floor_id}", token=admin_token)

        assert db.query_one("SELECT id FROM seats WHERE id = %s", (seat_id,)) is None
        assert db.query_one("SELECT id FROM buildings WHERE id = %s", (building_id,)) is not None


class TestFacilityAuthorization:
    """Everyone reads the estate; only an admin changes it."""

    def test_employee_reads_buildings(self, invoke, registered_user):
        status, _ = invoke("GET", "/api/v1/buildings", token=registered_user["token"])

        assert status == 200

    def test_engineer_reads_buildings(self, invoke, engineer_user):
        status, _ = invoke("GET", "/api/v1/buildings", token=engineer_user["token"])

        assert status == 200

    def test_employee_reads_floors_seats(self, invoke, registered_user, facility):
        status, _ = invoke(
            "GET",
            f"/api/v1/buildings/{facility['building_id']}/floors",
            token=registered_user["token"],
        )
        assert status == 200

        status, _ = invoke(
            "GET", f"/api/v1/floors/{facility['floor_id']}/seats", token=registered_user["token"]
        )
        assert status == 200

    def test_employee_cannot_create_building(self, invoke, registered_user):
        status, body = invoke(
            "POST", "/api/v1/buildings", {"name": _name("nope")}, token=registered_user["token"]
        )

        assert status == 403
        assert body["error"] == "forbidden"

    def test_engineer_cannot_create_building(self, invoke, engineer_user):
        status, _ = invoke(
            "POST", "/api/v1/buildings", {"name": _name("nope")}, token=engineer_user["token"]
        )

        assert status == 403

    def test_employee_cannot_create_children(self, invoke, registered_user, facility):
        status, _ = invoke(
            "POST",
            "/api/v1/floors",
            {"building_id": facility["building_id"], "name": "Sneaky"},
            token=registered_user["token"],
        )
        assert status == 403

        status, _ = invoke(
            "POST",
            "/api/v1/seats",
            {"floor_id": facility["floor_id"], "code": "X-1"},
            token=registered_user["token"],
        )
        assert status == 403

    def test_employee_cannot_delete(self, invoke, registered_user, facility):
        status, _ = invoke(
            "DELETE",
            f"/api/v1/buildings/{facility['building_id']}",
            token=registered_user["token"],
        )

        assert status == 403

    def test_read_requires_auth(self, invoke):
        status, _ = invoke("GET", "/api/v1/buildings")

        assert status == 401
