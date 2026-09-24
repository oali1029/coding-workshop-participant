"""Incident counts for the Facility Admin dashboard.

Every figure is aggregated by PostgreSQL. The browser is never sent the incident
list to count for itself, so the numbers stay correct as the dataset grows and
no unauthorised row is shipped to the client just to be tallied.

Admin-only, enforced by the route table.

Buildings: incidents whose facility was later deleted keep a NULL building_id
(ON DELETE SET NULL, from Slice 5). They are grouped under
ARCHIVED_BUILDING_LABEL rather than dropped, so the per-building figures always
add up to the total. The stored location_snapshot is deliberately not parsed —
it is display text describing where something was, not a reliable key.
"""

from typing import Any

from .. import db
from ..http import Request, ok
from .incidents import CATEGORIES, STATUSES

#: Bucket for incidents whose building has since been deleted.
ARCHIVED_BUILDING_LABEL = "Archived / Removed Location"


def _counts_by(column: str) -> dict[str, int]:
    """Count incidents grouped by one column.

    Args:
        column: A column name. Never taken from user input — the two call sites
            pass literals, so no value from a request reaches the SQL text.
    """
    rows = db.query_all(
        f"SELECT {column} AS key, COUNT(*) AS n FROM incidents GROUP BY {column}"
    )
    return {row["key"]: row["n"] for row in rows}


def summary(request: Request) -> dict[str, Any]:
    """Return incident totals by status, category and building.

    Status and category include every possible value with a zero where nothing
    matched, so the dashboard renders a stable set of cards instead of rows
    appearing and disappearing as data changes.
    """
    total = db.query_one("SELECT COUNT(*) AS n FROM incidents")["n"]

    by_status = _counts_by("status")
    by_category = _counts_by("category")

    # LEFT JOIN so detached incidents survive the grouping; an inner join would
    # silently drop them and the building figures would no longer sum to total.
    building_rows = db.query_all(
        """
        SELECT b.name AS name, COUNT(*) AS n
        FROM incidents i
        LEFT JOIN buildings b ON b.id = i.building_id
        GROUP BY b.name
        ORDER BY COUNT(*) DESC, b.name
        """
    )

    by_building = [
        {"building": row["name"] or ARCHIVED_BUILDING_LABEL, "count": row["n"]}
        for row in building_rows
    ]

    return ok(
        {
            "total": total,
            "by_status": {status: by_status.get(status, 0) for status in STATUSES},
            "by_category": {
                category: by_category.get(category, 0) for category in CATEGORIES
            },
            "by_building": by_building,
        }
    )
