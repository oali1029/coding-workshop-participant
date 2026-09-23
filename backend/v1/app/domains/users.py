"""User administration: listing accounts and changing roles.

Facility Admin only. This is what makes the ENGINEER role reachable at all —
registration always creates an EMPLOYEE, so without this endpoint no engineer
could ever exist, and nothing could be assigned to one in a later slice.

Scope is deliberately narrow. Only EMPLOYEE and ENGINEER can be set, and only
on a user who currently holds one of those roles. Administrator accounts are
managed separately, which also means an admin cannot change their own role and
lock everyone out of administration.
"""

import logging
from typing import Any

from .. import db, security
from ..errors import ForbiddenError, NotFoundError, ValidationError
from ..http import Request, ok

logger = logging.getLogger(__name__)

# The only roles this endpoint may read or write. FACILITY_ADMIN is absent on
# purpose: promoting or demoting administrators is a separate concern with its
# own safety questions (who may remove the last admin?), handled in a later
# slice.
MANAGEABLE_ROLES = (security.ROLE_EMPLOYEE, security.ROLE_ENGINEER)

# Listed explicitly so password_hash cannot leak, and so a sensitive column
# added by a future migration is excluded by default rather than included.
_USER_COLUMNS = "id, email, full_name, role, is_active, created_at"


def list_all(request: Request) -> dict[str, Any]:
    """List every account, so an admin can find who to promote.

    Sorted by name because this list is read by a person looking someone up,
    not by a machine. No pagination: ACME's staff list is small, and search and
    filtering belong to a later slice.
    """
    rows = db.query_all(f"SELECT {_USER_COLUMNS} FROM users ORDER BY full_name")

    return ok({"users": rows})


def list_engineers(request: Request) -> dict[str, Any]:
    """List the people an incident can be assigned to.

    Only active users whose exact role is ENGINEER. Admins are excluded: they
    can act on any incident without being assigned one, so assigning to them
    would add nothing.

    This populates the admin's assignee dropdown, but the same rule is checked
    again when an assignment is actually made — the dropdown is convenience, not
    a control.
    """
    rows = db.query_all(
        """
        SELECT id, full_name, email
        FROM users
        WHERE role = %s AND is_active = TRUE
        ORDER BY full_name
        """,
        (security.ROLE_ENGINEER,),
    )

    return ok({"engineers": rows})


def set_role(request: Request) -> dict[str, Any]:
    """Promote an employee to engineer, or demote an engineer back.

    Takes effect immediately for the affected user: every authenticated request
    re-reads the role from the database rather than trusting the role inside
    the caller's token, so they do not need to sign in again.

    Raises:
        NotFoundError: the id is not a number, or no such user.
        ValidationError: the requested role is missing or not manageable here.
        ForbiddenError: the target is an administrator.
    """
    try:
        user_id = int(request.path_params["id"])
    except (KeyError, ValueError):
        raise NotFoundError("User not found.")

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

    row = db.query_one(
        f"""
        UPDATE users
        SET role = %s, updated_at = now()
        WHERE id = %s
        RETURNING {_USER_COLUMNS}
        """,
        (requested_role, user_id),
    )

    logger.info(
        "Admin %s changed user %s role from %s to %s",
        request.user["id"],
        user_id,
        target["role"],
        requested_role,
    )

    return ok({"user": row})
