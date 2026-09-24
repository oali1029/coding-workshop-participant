"""Reporting, tracking, assigning and working facility incidents.

Three rules are enforced here rather than trusted from the client:

*The reporter is taken from the verified token*, never from the request body, so
nobody can file an incident in a colleague's name.

*New incidents are always OPEN.* Status is not read from the body on create.

*Only an active ENGINEER can be an assignee*, checked against the database at the
moment of assignment rather than trusting the dropdown the admin saw.

Three lists, deliberately distinct — conflating them would lose an engineer sight
of the broken tap they personally reported:

    list_mine      incidents I reported          every role
    list_assigned  work assigned to me           engineers only
    list_all       the whole organisation        admins only

Admins are never assignees. They can act on any incident without one, so an
"assigned to me" queue would always be empty for them.
"""

import logging
from typing import Any

from .. import db, security
from ..errors import ForbiddenError, NotFoundError, ValidationError
from ..http import Request, created, ok, require_text

logger = logging.getLogger(__name__)

CATEGORIES = ("TECHNOLOGY", "ELECTRICAL", "PLUMBING", "HVAC", "FURNITURE", "OTHER")
PRIORITIES = ("LOW", "MEDIUM", "HIGH")

STATUS_OPEN = "OPEN"
STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_BLOCKED = "BLOCKED"
STATUS_RESOLVED = "RESOLVED"
STATUS_CLOSED = "CLOSED"

STATUSES = (STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_BLOCKED, STATUS_RESOLVED, STATUS_CLOSED)

# The workflow expressed as two permission sets rather than a state machine.
#
# RESOLVED means "the engineer believes this is fixed, submitted for review";
# CLOSED means "an admin reviewed it and accepted it". Because those are
# decisions by different people, the rule is simply *who may set what* — no
# transition graph is needed, and the admin's review outcomes fall out of it:
# accept by setting CLOSED, or send back by setting OPEN or IN_PROGRESS.
ENGINEER_SETTABLE_STATUSES = frozenset(
    {STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_BLOCKED, STATUS_RESOLVED}
)
ADMIN_SETTABLE_STATUSES = frozenset(STATUSES)

DEFAULT_PRIORITY = "MEDIUM"
INITIAL_STATUS = STATUS_OPEN

MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 5000
MAX_LOCATION_LENGTH = 200
MAX_REASON_LENGTH = 500

# The assignee filter value meaning "nobody". A word rather than an id, because
# there is no id for absence.
UNASSIGNED = "unassigned"

# Statuses from which a reporter may ask for their incident to be escalated.
# A finished ticket cannot be made more urgent; it can be reopened instead.
ESCALATABLE_STATUSES = frozenset({STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_BLOCKED})

# One SELECT shared by every read, so all four endpoints return the same shape.
#
# The reporter join is inner — created_by is NOT NULL, so there is always one.
# The assignee join is LEFT, because an unassigned incident must still appear;
# an inner join would silently hide every incident awaiting triage.
#
# Columns are listed explicitly rather than SELECT *, so a sensitive column added
# to either table by a future migration is excluded by default.
_INCIDENT_SELECT = """
    SELECT
        i.id, i.title, i.description, i.category, i.priority, i.status, i.location,
        i.created_by, i.assignee_id, i.created_at, i.updated_at,
        i.building_id, i.floor_id, i.seat_id, i.location_snapshot,
        i.acknowledged_at, i.assigned_at, i.resolved_at, i.closed_at,
        i.escalation_requested, i.escalation_reason, i.escalated_at,
        i.blocked_reason,
        reporter.full_name AS reporter_name,
        reporter.email     AS reporter_email,
        assignee.full_name AS assignee_name,
        assignee.email     AS assignee_email,
        building.name      AS building_name,
        floor.name         AS floor_name,
        seat.code          AS seat_code
    FROM incidents i
    JOIN users reporter ON reporter.id = i.created_by
    LEFT JOIN users assignee ON assignee.id = i.assignee_id
    LEFT JOIN buildings building ON building.id = i.building_id
    LEFT JOIN floors floor ON floor.id = i.floor_id
    LEFT JOIN seats seat ON seat.id = i.seat_id
"""


def _require_choice(body: dict[str, Any], field: str, allowed: tuple[str, ...]) -> str:
    """Read a required value that must be one of a fixed set.

    Upper-cased before checking so the API accepts "plumbing" as well as
    "PLUMBING"; the database CHECK constraints only permit the canonical form.
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

    Blank becomes None so the database holds a real NULL rather than an empty
    string, keeping "no location given" a single condition to test.
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


def _resolve_location(body: dict[str, Any]) -> dict[str, Any]:
    """Validate the reported location and return the ids plus a readable snapshot.

    Building and floor are required; a seat is not, because elevators, bathrooms, and sinks do not have seats.

    One joined query resolves all three at once and proves they belong together.
    Validating them separately would let a crafted request file an incident at
    "Building A / Floor 9 of Building B".

    The snapshot ("Building A > Floor 3 > A-312") is stored on the incident so
    the location still reads correctly if the facility is later deleted.
    """
    building_id = _required_id(body, "building_id")
    floor_id = _required_id(body, "floor_id")

    seat_id = body.get("seat_id")
    if seat_id is not None:
        try:
            seat_id = int(seat_id)
        except (TypeError, ValueError):
            raise ValidationError("Invalid seat.", details={"field": "seat_id"})

    row = db.query_one(
        """
        SELECT b.name AS building_name, f.name AS floor_name, s.code AS seat_code
        FROM buildings b
        JOIN floors f ON f.id = %s AND f.building_id = b.id
        LEFT JOIN seats s ON s.id = %s AND s.floor_id = f.id
        WHERE b.id = %s
        """,
        (floor_id, seat_id, building_id),
    )

    if row is None:
        # Covers a missing building, a missing floor, and a floor belonging to a
        # different building. One message for all three so the endpoint cannot be
        # used to probe which ids exist.
        raise ValidationError(
            "Select a valid building and a floor within it.",
            details={"field": "floor_id"},
        )

    # The LEFT JOIN yields a row even when the seat is wrong, so check separately.
    if seat_id is not None and row["seat_code"] is None:
        raise ValidationError(
            "The selected seat is not on that floor.", details={"field": "seat_id"}
        )

    parts = [row["building_name"], row["floor_name"]]
    if row["seat_code"]:
        parts.append(row["seat_code"])

    return {
        "building_id": building_id,
        "floor_id": floor_id,
        "seat_id": seat_id,
        "snapshot": " > ".join(parts),
    }


def _required_id(body: dict[str, Any], field: str) -> int:
    """Read a required foreign key from the request body."""
    try:
        return int(body[field])
    except (KeyError, TypeError, ValueError):
        raise ValidationError("This field is required.", details={"field": field})


def build_filters(query: dict[str, str], allow_assignee: bool) -> tuple[list[str], list[Any]]:
    """Turn query parameters into SQL conditions and their values.

    Shared by all three list endpoints so the filters behave identically
    wherever they appear. What differs between the endpoints is the scoping
    clause each one adds — ``created_by = me``, ``assignee_id = me``, or nothing
    for an admin — and that stays in the handler where it is easy to audit. This
    helper can only narrow a result set, never widen one.

    Only fixed fragments reach the SQL text; every value is a parameter.

    Args:
        allow_assignee: whether to honour the ``assignee`` parameter. False for
            the personal lists, where the assignee is already fixed by scope.

    Raises:
        ValidationError: a filter value outside its permitted set.
    """
    conditions: list[str] = []
    params: list[Any] = []

    search = (query.get("q") or "").strip()
    if search:
        # ILIKE is case-insensitive and needs no extension. At this scale a scan
        # is fine; a trigram index would be the next step if it ever is not.
        conditions.append(
            """(
                i.title ILIKE %s OR i.description ILIKE %s
                OR reporter.full_name ILIKE %s OR assignee.full_name ILIKE %s
            )"""
        )
        params.extend([f"%{_escape_like(search)}%"] * 4)

    for field, column, allowed in (
        ("status", "i.status", STATUSES),
        ("category", "i.category", CATEGORIES),
        ("priority", "i.priority", PRIORITIES),
    ):
        value = (query.get(field) or "").strip().upper()
        if not value:
            continue
        if value not in allowed:
            raise ValidationError(
                f"Must be one of: {', '.join(allowed)}.", details={"field": field}
            )
        conditions.append(f"{column} = %s")
        params.append(value)

    building = (query.get("building") or "").strip()
    if building:
        try:
            building_id = int(building)
        except ValueError:
            raise ValidationError("Invalid building.", details={"field": "building"})
        conditions.append("i.building_id = %s")
        params.append(building_id)

    assignee = (query.get("assignee") or "").strip()
    if assignee and allow_assignee:
        if assignee.lower() == UNASSIGNED:
            conditions.append("i.assignee_id IS NULL")
        else:
            try:
                assignee_id = int(assignee)
            except ValueError:
                raise ValidationError("Invalid assignee.", details={"field": "assignee"})
            conditions.append("i.assignee_id = %s")
            params.append(assignee_id)

    return conditions, params


def _listing(scope_sql: str, scope_params: list[Any], request: Request,
             allow_assignee: bool = False) -> dict[str, Any]:
    """Run one of the three incident lists: scope first, then optional filters.

    The scope clause is always present and always first, so a filter can never
    remove the restriction that decides whose incidents these are.
    """
    conditions, params = build_filters(request.query, allow_assignee)

    where = " AND ".join([*( [scope_sql] if scope_sql else [] ), *conditions])
    where_sql = f" WHERE {where}" if where else ""

    rows = db.query_all(
        f"{_INCIDENT_SELECT}{where_sql} ORDER BY i.created_at DESC",
        tuple([*scope_params, *params]),
    )

    return ok({"incidents": rows})


def _escape_like(value: str) -> str:
    """Make a search term match literally inside an ILIKE pattern.

    ``%`` and ``_`` are wildcards in LIKE, so a search for "50%" would otherwise
    match almost everything. Backslash is PostgreSQL's default escape character,
    so it has to be escaped first or it would escape the escapes.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _incident_id(request: Request) -> int:
    """Read the {id} path parameter as a number.

    A non-numeric id is a 404 rather than a 400: it addresses nothing, and
    reporting it differently would distinguish "malformed" from "not yours".
    """
    try:
        return int(request.path_params["id"])
    except (KeyError, ValueError):
        raise NotFoundError("Incident not found.")


def _fetch(incident_id: int) -> dict[str, Any] | None:
    """Load one incident in the standard response shape."""
    return db.query_one(f"{_INCIDENT_SELECT} WHERE i.id = %s", (incident_id,))


def create(request: Request) -> dict[str, Any]:
    """Report a new incident. Returns 201 with ``{"incident": {...}}``."""
    body = request.json_body()

    title = require_text(body, "title", MAX_TITLE_LENGTH)
    description = require_text(body, "description", MAX_DESCRIPTION_LENGTH)
    category = _require_choice(body, "category", CATEGORIES)
    location = _optional_text(body, "location", MAX_LOCATION_LENGTH)

    # Optional: someone reporting a problem should not be forced to triage it.
    priority = DEFAULT_PRIORITY
    if body.get("priority") is not None:
        priority = _require_choice(body, "priority", PRIORITIES)

    # Note what is absent: nothing reads body["status"], body["created_by"] or
    # body["assignee_id"]. Status is a constant, the reporter comes from the
    # token the router verified, and assignment is an admin action afterwards.
    # Where it happened. Building and floor are required; the seat is not.
    place = _resolve_location(body)

    row = db.query_one(
        """
        INSERT INTO incidents (
            title, description, category, priority, status, location, created_by,
            building_id, floor_id, seat_id, location_snapshot
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            title,
            description,
            category,
            priority,
            INITIAL_STATUS,
            location,
            request.user["id"],
            place["building_id"],
            place["floor_id"],
            place["seat_id"],
            place["snapshot"],
        ),
    )

    logger.info("User %s reported incident %s", request.user["id"], row["id"])

    # Re-read through the shared SELECT so create returns exactly the shape the
    # other endpoints do. RETURNING cannot perform the joins.
    return created({"incident": _fetch(row["id"])})


def list_mine(request: Request) -> dict[str, Any]:
    """Incidents the signed-in user reported, newest first, optionally filtered.

    Creator-scoped for every role, permanently. The scope clause is the
    authorization: no filter can widen it, so no code path here returns another
    user's incidents.

    Filters: q, status, category, priority, building. Not assignee — every
    incident in this list is already the caller's own report.
    """
    return _listing("i.created_by = %s", [request.user["id"]], request)


def list_assigned(request: Request) -> dict[str, Any]:
    """The engineer's work queue: incidents assigned to them, newest first.

    Restricted to ENGINEER by the route table. Separate from ``list_mine`` so an
    engineer who reports a fault and is assigned a different one sees each in the
    right place — and sees a ticket in both if they were assigned their own report.

    Same filters as list_mine; the assignee is fixed by the scope.
    """
    return _listing("i.assignee_id = %s", [request.user["id"]], request)


def list_all(request: Request) -> dict[str, Any]:
    """Every incident in the organisation, newest first, optionally filtered.

    The Facility Admin's oversight view. Restricted to FACILITY_ADMIN by the
    route table, so there is no scope clause — an admin sees everything.

    Filters: q, status, category, priority, building, and assignee (an engineer
    id, or "unassigned"). All optional, combined with AND. Filtering happens in
    PostgreSQL rather than the browser, so the client never receives rows it
    then hides.
    """
    return _listing("", [], request, allow_assignee=True)


def get_one(request: Request) -> dict[str, Any]:
    """Return one incident: your own, one assigned to you, or any if an admin.

    Raises:
        NotFoundError: unknown id, or an incident the caller has no claim on.
            A 403 would confirm it exists, letting someone probe ids.
    """
    incident_id = _incident_id(request)
    row = _fetch(incident_id)

    if row is None or not may_view(request.user, row):
        raise NotFoundError("Incident not found.")

    return ok({"incident": row})


def may_view(user: dict[str, Any], incident: dict[str, Any]) -> bool:
    """Whether this user may see this incident.

    Three independent claims: you reported it, it is assigned to you, or you are
    an admin overseeing everything. Public because comments apply the same rule.
    """
    if user["role"] == security.ROLE_FACILITY_ADMIN:
        return True

    return user["id"] in (incident["created_by"], incident["assignee_id"])


def _resolve_assignee(body: dict[str, Any], current_assignee_id: int | None = None) -> int | None:
    """Validate the requested assignee and return their id, or None to unassign.

    Only an **active user whose exact role is ENGINEER** may hold work. Checked
    against the database here rather than trusted from the admin's dropdown: the
    client could send any id, and a user's role may have changed since the page
    loaded.

    Admins are deliberately not assignable — they can act on any incident without
    being assigned, so an assignment would add nothing.

    An engineer marked unavailable takes no *new* work, but an assignment they
    already hold is left alone: re-sending the same assignee is accepted, so
    editing an incident's status does not force the admin to move its ticket.

    Args:
        current_assignee_id: who holds the incident now, used for that exemption.
    """
    value = body["assignee_id"]

    # An explicit null means "unassign", which is a legitimate admin action.
    if value is None:
        return None

    try:
        assignee_id = int(value)
    except (TypeError, ValueError):
        raise ValidationError(
            "Assignee must be a user id.", details={"field": "assignee_id"}
        )

    candidate = db.query_one(
        "SELECT id, role, is_active, is_available FROM users WHERE id = %s", (assignee_id,)
    )

    if (
        candidate is None
        or not candidate["is_active"]
        or candidate["role"] != security.ROLE_ENGINEER
    ):
        # One message for all three failures, so this cannot be used to probe
        # which user ids exist or what roles they hold.
        raise ValidationError(
            "Incidents can only be assigned to an active engineer.",
            details={"field": "assignee_id"},
        )

    if not candidate["is_available"] and candidate["id"] != current_assignee_id:
        # A distinct message from the one above: this is a real engineer the
        # admin can see, so being told why is useful rather than a leak.
        raise ValidationError(
            "That engineer is marked unavailable and cannot take new work.",
            details={"field": "assignee_id"},
        )

    return candidate["id"]


def update(request: Request) -> dict[str, Any]:
    """Change an incident's status, assignee, priority, or blocked reason.

    Engineers may work incidents assigned to them; admins may act on any. The
    route table already restricted this to those two roles, so the checks here
    are about *which* incident and *which* fields.

    Priority is admin-only. An employee asks for urgency through an escalation
    request (see request_escalation) and an admin decides; letting the engineer
    doing the work re-rank it would undo that conversation.

    Entering BLOCKED requires a reason, so "which incidents are blocked and why"
    is always answerable. Leaving BLOCKED clears it, so a stale reason can never
    be shown against a ticket that is moving again.

    Raises:
        NotFoundError: unknown incident, or one the caller has no claim on.
        ForbiddenError: assigning or re-prioritising without being an admin,
            setting a status the caller's role may not set, or an engineer
            touching a closed ticket.
        ValidationError: nothing to change, an invalid value, or BLOCKED without
            a reason.
    """
    incident_id = _incident_id(request)
    body = request.json_body()

    is_admin = request.user["role"] == security.ROLE_FACILITY_ADMIN

    current = db.query_one(
        "SELECT id, status, assignee_id FROM incidents WHERE id = %s", (incident_id,)
    )

    if current is None:
        raise NotFoundError("Incident not found.")

    # An engineer may only touch their own assigned work. 404 rather than 403,
    # consistent with get_one — we never confirm an incident exists to someone
    # with no claim on it.
    if not is_admin and current["assignee_id"] != request.user["id"]:
        raise NotFoundError("Incident not found.")

    # CLOSED is a Facility Admin's acceptance that the work is complete. An
    # engineer must not be able to undo that; only an admin may reopen.
    if not is_admin and current["status"] == STATUS_CLOSED:
        raise ForbiddenError("This incident has been closed and can only be reopened by an admin.")

    wants_status = "status" in body
    wants_assignee = "assignee_id" in body
    wants_priority = "priority" in body

    if not (wants_status or wants_assignee or wants_priority):
        raise ValidationError("Provide a status, an assignee or a priority to change.")

    # Both rejected outright rather than applying the rest of the request, so a
    # refused call changes nothing at all.
    if wants_assignee and not is_admin:
        raise ForbiddenError("Only a Facility Admin can assign incidents.")

    if wants_priority and not is_admin:
        raise ForbiddenError(
            "Only a Facility Admin can change priority. Request an escalation instead."
        )

    # Build the SET clause from a fixed set of fragments. Nothing from the
    # request body ever becomes SQL text — only the values, as parameters.
    assignments = ["updated_at = now()"]
    params: list[Any] = []

    # Any change made here is by an engineer or an admin, which is what
    # acknowledgement means: someone responsible has picked the ticket up.
    # COALESCE keeps the first such moment forever — a reopened ticket must not
    # claim it was acknowledged the second time round.
    assignments.append("acknowledged_at = COALESCE(acknowledged_at, now())")

    if wants_status:
        status = _require_choice(body, "status", STATUSES)
        allowed = ADMIN_SETTABLE_STATUSES if is_admin else ENGINEER_SETTABLE_STATUSES

        if status not in allowed:
            # Reached when an engineer asks for CLOSED. 403 rather than 400: the
            # value is valid, the caller simply may not set it.
            raise ForbiddenError(f"Only a Facility Admin can set an incident to {status}.")

        assignments.append("status = %s")
        params.append(status)

        if status == STATUS_BLOCKED:
            reason = _optional_text(body, "blocked_reason", MAX_REASON_LENGTH)
            if reason is None:
                raise ValidationError(
                    "Say why this incident is blocked.",
                    details={"field": "blocked_reason"},
                )
            assignments.append("blocked_reason = %s")
            params.append(reason)
        else:
            assignments.append("blocked_reason = NULL")

        # First time each milestone is reached, never overwritten afterwards.
        if status == STATUS_RESOLVED:
            assignments.append("resolved_at = COALESCE(resolved_at, now())")
        if status == STATUS_CLOSED:
            assignments.append("closed_at = COALESCE(closed_at, now())")

    if wants_assignee:
        assignee_id = _resolve_assignee(body, current["assignee_id"])
        assignments.append("assignee_id = %s")
        params.append(assignee_id)

        if assignee_id is not None:
            assignments.append("assigned_at = COALESCE(assigned_at, now())")

    if wants_priority:
        assignments.append("priority = %s")
        params.append(_require_choice(body, "priority", PRIORITIES))

    params.append(incident_id)

    db.execute(
        f"UPDATE incidents SET {', '.join(assignments)} WHERE id = %s", tuple(params)
    )

    logger.info(
        "User %s updated incident %s (status=%s assignee=%s priority=%s)",
        request.user["id"],
        incident_id,
        body.get("status") if wants_status else "unchanged",
        body.get("assignee_id") if wants_assignee else "unchanged",
        body.get("priority") if wants_priority else "unchanged",
    )

    return ok({"incident": _fetch(incident_id)})


def request_escalation(request: Request) -> dict[str, Any]:
    """The reporter asks for their own incident to be treated as more urgent.

    Deliberately not a priority change. The employee states a case and an admin
    decides — which keeps priority meaningful and stops the field becoming a
    race between reporters.

    Restricted to the reporter of an unfinished incident. An admin who wants
    more urgency simply sets the priority.

    Raises:
        NotFoundError: unknown incident, or not the caller's own report.
        ForbiddenError: the incident is already resolved or closed.
        ValidationError: no reason given.
    """
    incident_id = _incident_id(request)
    body = request.json_body()

    incident = db.query_one(
        "SELECT id, created_by, status FROM incidents WHERE id = %s", (incident_id,)
    )

    # Reporter only — not the assigned engineer, not an admin. 404 rather than
    # 403 so the endpoint cannot be used to discover which incidents exist.
    if incident is None or incident["created_by"] != request.user["id"]:
        raise NotFoundError("Incident not found.")

    if incident["status"] not in ESCALATABLE_STATUSES:
        raise ForbiddenError("This incident is already finished and cannot be escalated.")

    reason = require_text(body, "reason", MAX_REASON_LENGTH)

    db.execute(
        """
        UPDATE incidents
        SET escalation_requested = TRUE,
            escalation_reason = %s,
            escalated_at = now(),
            updated_at = now()
        WHERE id = %s
        """,
        (reason, incident_id),
    )

    logger.info("User %s requested escalation of incident %s", request.user["id"], incident_id)

    return ok({"incident": _fetch(incident_id)})


def acknowledge_escalation(request: Request) -> dict[str, Any]:
    """The admin marks an escalation request as handled. Facility Admin only.

    Clears the flag but keeps the reason and the timestamp, so the record still
    says what was asked for and when — the request is answered, not erased.
    """
    incident_id = _incident_id(request)

    row = db.query_one(
        """
        UPDATE incidents
        SET escalation_requested = FALSE, updated_at = now()
        WHERE id = %s
        RETURNING id
        """,
        (incident_id,),
    )

    if row is None:
        raise NotFoundError("Incident not found.")

    logger.info("Admin %s acknowledged escalation on incident %s", request.user["id"], incident_id)

    return ok({"incident": _fetch(incident_id)})


def delete(request: Request) -> dict[str, Any]:
    """Permanently remove an incident and its comments. Facility Admin only.

    Distinct from CLOSED, which records that the work was done. This removes the
    record entirely — for a duplicate, a test ticket or a report filed in error —
    so it is allowed from any status, including CLOSED.

    Comments go with it through ON DELETE CASCADE on incident_comments (migration
    6) rather than a second statement here: one DELETE means there is no window
    in which the incident is gone but its comments are not.

    Nothing else is touched. The incident's references to its reporter, assignee
    and location point outward, so removing this row cannot affect those records.

    Raises:
        NotFoundError: no incident with that id. Unlike the other handlers there
            is no visibility rule to apply — the route is admin-only, and admins
            may see everything.
    """
    incident_id = _incident_id(request)

    # Counted first: after the DELETE the rows are gone and cannot be counted.
    comments = db.query_one(
        "SELECT COUNT(*) AS n FROM incident_comments WHERE incident_id = %s", (incident_id,)
    )

    row = db.query_one("DELETE FROM incidents WHERE id = %s RETURNING id", (incident_id,))

    if row is None:
        raise NotFoundError("Incident not found.")

    logger.info(
        "Admin %s deleted incident %s (%s comments removed)",
        request.user["id"],
        incident_id,
        comments["n"],
    )

    return ok({"deleted": incident_id, "comments_deleted": comments["n"]})
