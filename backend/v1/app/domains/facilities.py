"""Buildings, floors and seats — the physical estate.

Three levels of the same simple CRUD, so the handlers are written out rather
than generated from a shared helper: it keeps each SQL statement visible.

Everyone can read this data because every reporter needs the dropdowns. Only a
Facility Admin can change it, which the route table enforces.

Deleting a building removes its floors and seats (ON DELETE CASCADE) but only
detaches it from incidents (ON DELETE SET NULL), so history survives. Delete
responses report how many incidents were affected, so the admin sees the cost.
"""

import logging
from typing import Any

from psycopg.errors import UniqueViolation

from .. import db
from ..errors import ConflictError, NotFoundError, ValidationError
from ..http import Request, created, ok, require_text

logger = logging.getLogger(__name__)

MAX_NAME_LENGTH = 120
MAX_ADDRESS_LENGTH = 300
MAX_SEAT_CODE_LENGTH = 40


def _path_id(request: Request) -> int:
    """Read the {id} path parameter as a number, or 404."""
    try:
        return int(request.path_params["id"])
    except (KeyError, ValueError):
        raise NotFoundError("Not found.")


def _required_id(body: dict[str, Any], field: str) -> int:
    """Read a required foreign key from the body."""
    try:
        return int(body[field])
    except (KeyError, TypeError, ValueError):
        raise ValidationError("This field is required.", details={"field": field})


# ---------------------------------------------------------------------------
# Buildings
# ---------------------------------------------------------------------------
def list_buildings(request: Request) -> dict[str, Any]:
    """Every building, alphabetically — this list is read by a person."""
    rows = db.query_all(
        "SELECT id, name, address, created_at FROM buildings ORDER BY name"
    )
    return ok({"buildings": rows})


def create_building(request: Request) -> dict[str, Any]:
    """Add a building. Names are unique so the dropdown stays unambiguous."""
    body = request.json_body()
    name = require_text(body, "name", MAX_NAME_LENGTH)
    address = body.get("address")
    address = address.strip() if isinstance(address, str) and address.strip() else None

    if address and len(address) > MAX_ADDRESS_LENGTH:
        raise ValidationError(
            f"Address must be {MAX_ADDRESS_LENGTH} characters or fewer.",
            details={"field": "address"},
        )

    # ON CONFLICT + RETURNING makes insert-or-detect-duplicate atomic; checking
    # first would leave a gap for a concurrent insert of the same name.
    row = db.query_one(
        """
        INSERT INTO buildings (name, address) VALUES (%s, %s)
        ON CONFLICT (name) DO NOTHING
        RETURNING id, name, address, created_at
        """,
        (name, address),
    )

    if row is None:
        raise ConflictError("A building with this name already exists.")

    logger.info("Admin %s created building %s", request.user["id"], row["id"])
    return created({"building": row})


def update_building(request: Request) -> dict[str, Any]:
    """Rename a building or change its address."""
    building_id = _path_id(request)
    body = request.json_body()

    if "name" not in body and "address" not in body:
        raise ValidationError("Provide a name or address to change.")

    existing = db.query_one("SELECT id FROM buildings WHERE id = %s", (building_id,))
    if existing is None:
        raise NotFoundError("Building not found.")

    assignments = ["updated_at = now()"]
    params: list[Any] = []

    if "name" in body:
        assignments.append("name = %s")
        params.append(require_text(body, "name", MAX_NAME_LENGTH))

    if "address" in body:
        value = body["address"]
        assignments.append("address = %s")
        params.append(value.strip() if isinstance(value, str) and value.strip() else None)

    params.append(building_id)

    try:
        row = db.query_one(
            f"""
            UPDATE buildings SET {', '.join(assignments)} WHERE id = %s
            RETURNING id, name, address, created_at
            """,
            tuple(params),
        )
    except UniqueViolation:
        # UPDATE has no ON CONFLICT clause, so unlike the create handlers this
        # one has to catch the constraint failure and turn it into the same 409.
        raise ConflictError("A building with this name already exists.")

    return ok({"building": row})


def delete_building(request: Request) -> dict[str, Any]:
    """Remove a building, its floors and its seats.

    Incidents reported there are kept: their location ids become NULL and the
    stored location_snapshot continues to describe where the problem was.
    """
    building_id = _path_id(request)

    affected = db.query_one(
        "SELECT COUNT(*) AS n FROM incidents WHERE building_id = %s", (building_id,)
    )
    row = db.query_one("DELETE FROM buildings WHERE id = %s RETURNING id", (building_id,))

    if row is None:
        raise NotFoundError("Building not found.")

    logger.info(
        "Admin %s deleted building %s (%s incidents detached)",
        request.user["id"],
        building_id,
        affected["n"],
    )
    return ok({"deleted": building_id, "incidents_detached": affected["n"]})


# ---------------------------------------------------------------------------
# Floors
# ---------------------------------------------------------------------------
def list_floors(request: Request) -> dict[str, Any]:
    """Floors in one building — the second step of the location picker."""
    building_id = _path_id(request)

    if db.query_one("SELECT id FROM buildings WHERE id = %s", (building_id,)) is None:
        raise NotFoundError("Building not found.")

    rows = db.query_all(
        """
        SELECT id, building_id, name, created_at
        FROM floors WHERE building_id = %s ORDER BY name
        """,
        (building_id,),
    )
    return ok({"floors": rows})


def create_floor(request: Request) -> dict[str, Any]:
    """Add a floor to a building."""
    body = request.json_body()
    building_id = _required_id(body, "building_id")
    name = require_text(body, "name", MAX_NAME_LENGTH)

    if db.query_one("SELECT id FROM buildings WHERE id = %s", (building_id,)) is None:
        raise ValidationError("Building not found.", details={"field": "building_id"})

    row = db.query_one(
        """
        INSERT INTO floors (building_id, name) VALUES (%s, %s)
        ON CONFLICT (building_id, name) DO NOTHING
        RETURNING id, building_id, name, created_at
        """,
        (building_id, name),
    )

    if row is None:
        raise ConflictError("This building already has a floor with that name.")

    return created({"floor": row})


def update_floor(request: Request) -> dict[str, Any]:
    """Rename a floor. It cannot be moved to a different building."""
    floor_id = _path_id(request)
    body = request.json_body()
    name = require_text(body, "name", MAX_NAME_LENGTH)

    if db.query_one("SELECT id FROM floors WHERE id = %s", (floor_id,)) is None:
        raise NotFoundError("Floor not found.")

    try:
        row = db.query_one(
            """
            UPDATE floors SET name = %s, updated_at = now() WHERE id = %s
            RETURNING id, building_id, name, created_at
            """,
            (name, floor_id),
        )
    except UniqueViolation:
        raise ConflictError("This building already has a floor with that name.")

    return ok({"floor": row})


def delete_floor(request: Request) -> dict[str, Any]:
    """Remove a floor and its seats, detaching it from any incidents."""
    floor_id = _path_id(request)

    affected = db.query_one(
        "SELECT COUNT(*) AS n FROM incidents WHERE floor_id = %s", (floor_id,)
    )
    row = db.query_one("DELETE FROM floors WHERE id = %s RETURNING id", (floor_id,))

    if row is None:
        raise NotFoundError("Floor not found.")

    return ok({"deleted": floor_id, "incidents_detached": affected["n"]})


# ---------------------------------------------------------------------------
# Seats
# ---------------------------------------------------------------------------
def list_seats(request: Request) -> dict[str, Any]:
    """Seats on one floor — the optional third step of the location picker."""
    floor_id = _path_id(request)

    if db.query_one("SELECT id FROM floors WHERE id = %s", (floor_id,)) is None:
        raise NotFoundError("Floor not found.")

    rows = db.query_all(
        "SELECT id, floor_id, code, created_at FROM seats WHERE floor_id = %s ORDER BY code",
        (floor_id,),
    )
    return ok({"seats": rows})


def create_seat(request: Request) -> dict[str, Any]:
    """Add a seat to a floor."""
    body = request.json_body()
    floor_id = _required_id(body, "floor_id")
    code = require_text(body, "code", MAX_SEAT_CODE_LENGTH)

    if db.query_one("SELECT id FROM floors WHERE id = %s", (floor_id,)) is None:
        raise ValidationError("Floor not found.", details={"field": "floor_id"})

    row = db.query_one(
        """
        INSERT INTO seats (floor_id, code) VALUES (%s, %s)
        ON CONFLICT (floor_id, code) DO NOTHING
        RETURNING id, floor_id, code, created_at
        """,
        (floor_id, code),
    )

    if row is None:
        raise ConflictError("This floor already has a seat with that code.")

    return created({"seat": row})


def update_seat(request: Request) -> dict[str, Any]:
    """Change a seat's code. It cannot be moved to a different floor."""
    seat_id = _path_id(request)
    body = request.json_body()
    code = require_text(body, "code", MAX_SEAT_CODE_LENGTH)

    if db.query_one("SELECT id FROM seats WHERE id = %s", (seat_id,)) is None:
        raise NotFoundError("Seat not found.")

    try:
        row = db.query_one(
            """
            UPDATE seats SET code = %s, updated_at = now() WHERE id = %s
            RETURNING id, floor_id, code, created_at
            """,
            (code, seat_id),
        )
    except UniqueViolation:
        raise ConflictError("This floor already has a seat with that code.")

    return ok({"seat": row})


def delete_seat(request: Request) -> dict[str, Any]:
    """Remove a seat, detaching it from any incidents."""
    seat_id = _path_id(request)

    affected = db.query_one(
        "SELECT COUNT(*) AS n FROM incidents WHERE seat_id = %s", (seat_id,)
    )
    row = db.query_one("DELETE FROM seats WHERE id = %s RETURNING id", (seat_id,))

    if row is None:
        raise NotFoundError("Seat not found.")

    return ok({"deleted": seat_id, "incidents_detached": affected["n"]})
