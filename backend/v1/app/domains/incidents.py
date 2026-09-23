"""Reporting and viewing facility incidents.

Employees report a problem, then track it. This slice covers creating an
incident and reading your own; assignment, notes and status changes belong to
later slices.

Two rules are enforced here rather than trusted from the client:

*The reporter is taken from the verified token*, never from the request body.
Accepting a ``created_by`` field would let anyone file an incident in a
colleague's name.

*New incidents are always OPEN.* The status field is not read from the body at
all, so a client cannot create something already marked RESOLVED.

Visibility is creator-scoped for every role in this slice — you see what you
reported. Organisation-wide visibility for Facility Admins arrives with the
admin slice, and building it now would mean half-implementing a feature whose
requirements are not yet defined.
"""

import logging
from typing import Any

from .. import db
from ..errors import NotFoundError, ValidationError
from ..http import Request, created, ok, require_text

logger = logging.getLogger(__name__)

CATEGORIES = ("TECHNOLOGY", "ELECTRICAL", "PLUMBING", "HVAC", "FURNITURE", "OTHER")
PRIORITIES = ("LOW", "MEDIUM", "HIGH")

DEFAULT_PRIORITY = "MEDIUM"
INITIAL_STATUS = "OPEN"

MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 5000
MAX_LOCATION_LENGTH = 200

# Listed explicitly rather than SELECT *, so adding an internal column later
# cannot accidentally expose it through the API.
_INCIDENT_COLUMNS = """
    id, title, description, category, priority, status, location,
    created_by, created_at, updated_at
"""


def _require_choice(body: dict[str, Any], field: str, allowed: tuple[str, ...]) -> str:
    """Read a required value that must be one of a fixed set.

    Upper-cased before checking so the API accepts "plumbing" as well as
    "PLUMBING"; the database CHECK constraints only permit the canonical form.

    Raises:
        ValidationError: missing, or not one of ``allowed``.
    """
    value = body.get(field)

    if not isinstance(value, str) or not value.strip():
        raise ValidationError("This field is required.", details={"field": field})

    value = value.strip().upper()

    if value not in allowed:
        raise ValidationError(
            f"Must be one of: {', '.join(allowed)}.",
            details={"field": field},
        )

    return value


def _optional_text(body: dict[str, Any], field: str, max_length: int) -> str | None:
    """Read an optional string, returning None when absent or blank.

    Blank is normalised to None so the database holds a real NULL rather than
    an empty string, which keeps "no location given" a single condition to test.
    """
    value = body.get(field)

    if value is None or (isinstance(value, str) and not value.strip()):
        return None

    if not isinstance(value, str):
        raise ValidationError("This field must be text.", details={"field": field})

    value = value.strip()

    if len(value) > max_length:
        raise ValidationError(
            f"This field must be {max_length} characters or fewer.",
            details={"field": field},
        )

    return value


def create(request: Request) -> dict[str, Any]:
    """Report a new incident.

    Returns 201 with ``{"incident": {...}}``.
    """
    body = request.json_body()

    title = require_text(body, "title", MAX_TITLE_LENGTH)
    description = require_text(body, "description", MAX_DESCRIPTION_LENGTH)
    category = _require_choice(body, "category", CATEGORIES)
    location = _optional_text(body, "location", MAX_LOCATION_LENGTH)

    # Priority is optional; an employee reporting a problem should not be
    # forced to triage it.
    priority = DEFAULT_PRIORITY
    if body.get("priority") is not None:
        priority = _require_choice(body, "priority", PRIORITIES)

    # Note what is absent: nothing reads body["status"] or body["created_by"].
    # The status is a constant and the reporter comes from the token the router
    # already verified, so neither can be influenced by the request.
    row = db.query_one(
        f"""
        INSERT INTO incidents (title, description, category, priority, status, location, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING {_INCIDENT_COLUMNS}
        """,
        (
            title,
            description,
            category,
            priority,
            INITIAL_STATUS,
            location,
            request.user["id"],
        ),
    )

    logger.info("User %s reported incident %s", request.user["id"], row["id"])

    return created({"incident": row})


def list_mine(request: Request) -> dict[str, Any]:
    """List the incidents the signed-in user reported, newest first.

    The WHERE clause is the authorization: there is no code path that returns
    another user's incidents, so a filtering bug cannot leak them.
    """
    rows = db.query_all(
        f"""
        SELECT {_INCIDENT_COLUMNS}
        FROM incidents
        WHERE created_by = %s
        ORDER BY created_at DESC
        """,
        (request.user["id"],),
    )

    return ok({"incidents": rows})


def get_one(request: Request) -> dict[str, Any]:
    """Return one incident the signed-in user reported.

    Raises:
        NotFoundError: the id is not a number, does not exist, or belongs to
            someone else. All three give the same 404 deliberately — a 403 on
            the last case would confirm that an incident with that id exists,
            letting someone probe ids to learn how many have been filed.
    """
    try:
        incident_id = int(request.path_params["id"])
    except (KeyError, ValueError):
        raise NotFoundError("Incident not found.")

    # Ownership is part of the query rather than a check afterwards, so the row
    # is never loaded into memory unless the caller is entitled to it.
    row = db.query_one(
        f"""
        SELECT {_INCIDENT_COLUMNS}
        FROM incidents
        WHERE id = %s AND created_by = %s
        """,
        (incident_id, request.user["id"]),
    )

    if row is None:
        raise NotFoundError("Incident not found.")

    return ok({"incident": row})
