"""User administration: listing accounts and changing roles.

Facility Admin only. This is what makes the ENGINEER role reachable at all —
registration always creates an EMPLOYEE, so without this endpoint no engineer
could ever exist, and nothing could be assigned to one in a later slice.

Scope is deliberately narrow. Only EMPLOYEE and ENGINEER can be set, and only
on a user who currently holds one of those roles. Administrator accounts are
managed separately, which also means an admin cannot change their own role and
lock everyone out of administration.

Role changes have a consequence beyond the users table: a demoted engineer is
released from their live incidents, so the two writes are made together rather
than leaving a window where someone holds work they can no longer do.
"""

import logging
from typing import Any

from .. import db, security
from ..errors import ForbiddenError, NotFoundError, ValidationError
from ..http import Request, ok
from .incidents import STATUS_CLOSED

logger = logging.getLogger(__name__)

# The only roles this endpoint may read or write. FACILITY_ADMIN is absent on
# purpose: promoting or demoting administrators is a separate concern with its
# own safety questions (who may remove the last admin?), handled in a later
# slice.
MANAGEABLE_ROLES = (security.ROLE_EMPLOYEE, security.ROLE_ENGINEER)

# Listed explicitly so password_hash cannot leak, and so a sensitive column
# added by a future migration is excluded by default rather than included.
_USER_COLUMNS = "id, email, full_name, role, is_active, is_available, created_at"

# Release a demoted engineer's live work. CLOSED is excluded on purpose: a
# finished ticket is a record of who actually did it, and blanking that would
# rewrite history and distort any later report on past workload.
#
# The status is never touched — an OPEN ticket stays OPEN, it simply has nobody
# on it, which is the same state as a newly reported one awaiting triage.
# assigned_at is left alone too: it really was assigned once.
#
# RETURNING id makes the row count a fact from the database rather than a
# separate COUNT that could disagree with what was actually changed.
_UNASSIGN_ACTIVE_SQL = """
    UPDATE incidents
    SET assignee_id = NULL, updated_at = now()
    WHERE assignee_id = %s AND status <> %s
    RETURNING id
"""


def list_all(request: Request) -> dict[str, Any]:
    """List every account, so an admin can find who to promote.

    Sorted by name because this list is read by a person looking someone up,
    not by a machine. No pagination: ACME's staff list is small, and search and
    filtering belong to a later slice.
    """
    rows = db.query_all(f"SELECT {_USER_COLUMNS} FROM users ORDER BY full_name")

    return ok({"users": rows})


def list_engineers(request: Request) -> dict[str, Any]:
    """List the people an incident can be assigned to, with their current load.

    Only active users whose exact role is ENGINEER. Admins are excluded: they
    can act on any incident without being assigned one, so assigning to them
    would add nothing.

    Availability and the live ticket count come with the list so the admin
    chooses with the workload in front of them rather than guessing. Unavailable
    engineers are still listed — hiding them would leave the admin unable to see
    who is out — and the assignment endpoint refuses them.

    This populates the admin's assignee dropdown, but every rule is checked again
    when an assignment is actually made; the dropdown is convenience, not control.
    """
    rows = db.query_all(
        """
        SELECT
            u.id, u.full_name, u.email, u.is_available,
            COUNT(i.id) FILTER (WHERE i.status <> %s) AS active_count
        FROM users u
        LEFT JOIN incidents i ON i.assignee_id = u.id
        WHERE u.role = %s AND u.is_active = TRUE
        GROUP BY u.id, u.full_name, u.email, u.is_available
        ORDER BY u.full_name
        """,
        (STATUS_CLOSED, security.ROLE_ENGINEER),
    )

    return ok({"engineers": rows})


def set_availability(request: Request) -> dict[str, Any]:
    """Mark an engineer available or unavailable. Facility Admin only.

    The lightest possible answer to "which engineers are available?" — a single
    flag an admin keeps current, not a scheduling system. Unavailable means
    "give them no new work"; tickets they already hold stay with them, because
    reassigning someone's queue the moment they go on leave would lose the
    context they have on each one.

    Only engineers have availability. Setting it on an employee would record a
    fact about somebody who cannot hold work in the first place.

    Raises:
        NotFoundError: the id is not a number, or no such user.
        ValidationError: is_available missing or not a boolean.
        ForbiddenError: the target is not an engineer.
    """
    user_id = _path_user_id(request)
    body = request.json_body()
    value = body.get("is_available")

    if not isinstance(value, bool):
        raise ValidationError(
            "This field must be true or false.", details={"field": "is_available"}
        )

    target = db.query_one("SELECT id, role FROM users WHERE id = %s", (user_id,))

    if target is None:
        raise NotFoundError("User not found.")

    if target["role"] != security.ROLE_ENGINEER:
        raise ForbiddenError("Only engineers have an availability setting.")

    row = db.query_one(
        f"""
        UPDATE users
        SET is_available = %s, updated_at = now()
        WHERE id = %s
        RETURNING {_USER_COLUMNS}
        """,
        (value, user_id),
    )

    logger.info(
        "Admin %s set engineer %s availability to %s", request.user["id"], user_id, value
    )

    return ok({"user": row})


def _path_user_id(request: Request) -> int:
    """Read the {id} path parameter as a number, or 404."""
    try:
        return int(request.path_params["id"])
    except (KeyError, ValueError):
        raise NotFoundError("User not found.")


def set_role(request: Request) -> dict[str, Any]:
    """Promote an employee to engineer, or demote an engineer back.

    Takes effect immediately for the affected user: every authenticated request
    re-reads the role from the database rather than trusting the role inside
    the caller's token, so they do not need to sign in again.

    Demoting an engineer also releases every incident of theirs that is not
    CLOSED, in the same transaction. Otherwise a former engineer would keep
    appearing as the assignee on live tickets they can no longer open, and would
    keep counting towards the workload figures the admin assigns from. CLOSED
    incidents keep their assignee, because that is a record of who did the work.

    Returns 200 with ``{"user": {...}, "incidents_unassigned": n}``.

    Raises:
        NotFoundError: the id is not a number, or no such user.
        ValidationError: the requested role is missing or not manageable here.
        ForbiddenError: the target is an administrator.
    """
    user_id = _path_user_id(request)

    body = request.json_body()
    requested_role = body.get("role")

    if not isinstance(requested_role, str) or not requested_role.strip():
        raise ValidationError("This field is required.", details={"field": "role"})

    requested_role = requested_role.strip().upper()

    if requested_role not in MANAGEABLE_ROLES:
        raise ValidationError(
            f"Role must be one of: {', '.join(MANAGEABLE_ROLES)}.",
            details={"field": "role"},
        )

    target = db.query_one("SELECT id, role FROM users WHERE id = %s", (user_id,))

    if target is None:
        raise NotFoundError("User not found.")

    # Blocks demoting another administrator, and — because the caller is always
    # an admin — blocks changing your own role too, which would otherwise let
    # the only admin lock everyone out of administration.
    if target["role"] not in MANAGEABLE_ROLES:
        raise ForbiddenError("Administrator accounts cannot be changed here.")

    # Someone who is no longer an engineer must not still be holding live work:
    # it would sit in a queue they can no longer open, and it would count
    # against them in workload reporting.
    is_demotion = (
        target["role"] == security.ROLE_ENGINEER
        and requested_role != security.ROLE_ENGINEER
    )

    # Both writes in one transaction. Separately, a failure between them could
    # leave an ex-engineer still assigned to live tickets — the exact state this
    # change exists to prevent.
    with db.transaction() as cur:
        # Availability is reset on every role change so a re-promoted engineer
        # does not silently inherit an "unavailable" flag set months earlier.
        cur.execute(
            f"""
            UPDATE users
            SET role = %s, is_available = TRUE, updated_at = now()
            WHERE id = %s
            RETURNING {_USER_COLUMNS}
            """,
            (requested_role, user_id),
        )
        row = cur.fetchone()

        unassigned = 0
        if is_demotion:
            cur.execute(_UNASSIGN_ACTIVE_SQL, (user_id, STATUS_CLOSED))
            unassigned = len(cur.fetchall())

    logger.info(
        "Admin %s changed user %s role from %s to %s (%s active incidents unassigned)",
        request.user["id"],
        user_id,
        target["role"],
        requested_role,
        unassigned,
    )

    return ok({"user": row, "incidents_unassigned": unassigned})
