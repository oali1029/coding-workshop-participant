"""Conversation on an incident.

Who may read and write comments is exactly who may see the incident, so this
module reuses ``incidents.may_view`` rather than restating the rule: the
reporter, the assigned engineer, and any admin. An engineer gains nothing from
being an engineer — only from being assigned.

Comments are a permanent record. There is no edit or delete endpoint, so nobody
can rewrite what was said, including their own words.

A CLOSED incident keeps its comments readable but accepts no new ones. That
matches the rest of the workflow, where CLOSED is an admin's acceptance that the
work is finished; an admin who wants further discussion reopens the ticket
first. The rule applies to admins too, so the history cannot grow after the
ticket was declared complete.
"""

import logging
from typing import Any

from .. import db
from ..errors import ForbiddenError, NotFoundError, ValidationError
from ..http import Request, created, ok, require_text
from .incidents import STATUS_CLOSED, may_view

logger = logging.getLogger(__name__)

MAX_BODY_LENGTH = 2000

_COMMENT_SELECT = """
    SELECT
        c.id, c.incident_id, c.author_id, c.body, c.created_at,
        author.full_name AS author_name,
        author.role      AS author_role
    FROM incident_comments c
    JOIN users author ON author.id = c.author_id
"""


def _incident_for_comment(request: Request) -> dict[str, Any]:
    """Load the incident this request addresses, or 404.

    Returns 404 rather than 403 when the caller has no claim on the incident,
    matching the incident endpoints: a 403 would confirm that an incident with
    that id exists.
    """
    try:
        incident_id = int(request.path_params["id"])
    except (KeyError, ValueError):
        raise NotFoundError("Incident not found.")

    incident = db.query_one(
        "SELECT id, created_by, assignee_id, status FROM incidents WHERE id = %s",
        (incident_id,),
    )

    if incident is None or not may_view(request.user, incident):
        raise NotFoundError("Incident not found.")

    return incident


def list_for_incident(request: Request) -> dict[str, Any]:
    """Return an incident's comments, oldest first, so it reads as a conversation."""
    incident = _incident_for_comment(request)

    rows = db.query_all(
        f"{_COMMENT_SELECT} WHERE c.incident_id = %s ORDER BY c.created_at, c.id",
        (incident["id"],),
    )

    return ok({"comments": rows})


def create(request: Request) -> dict[str, Any]:
    """Add a comment to an incident.

    Raises:
        NotFoundError: unknown incident, or one the caller has no claim on.
        ForbiddenError: the incident is closed.
        ValidationError: blank, whitespace-only, or over-length body.
    """
    incident = _incident_for_comment(request)

    if incident["status"] == STATUS_CLOSED:
        raise ForbiddenError(
            "This incident is closed. An administrator must reopen it before "
            "further comments can be added."
        )

    # require_text trims and rejects blank or whitespace-only input, which is
    # the same validation every other text field in the API gets.
    body = require_text(request.json_body(), "body", MAX_BODY_LENGTH)

    row = db.query_one(
        """
        INSERT INTO incident_comments (incident_id, author_id, body)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (incident["id"], request.user["id"], body),
    )

    logger.info(
        "User %s commented on incident %s", request.user["id"], incident["id"]
    )

    # Re-read through the shared SELECT so the response carries the author's
    # name and role, exactly as the list endpoint does.
    comment = db.query_one(f"{_COMMENT_SELECT} WHERE c.id = %s", (row["id"],))

    return created({"comment": comment})
