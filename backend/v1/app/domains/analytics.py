"""Incident counts and lifecycle timings for the three dashboards.

Every figure is aggregated by PostgreSQL. No browser is ever sent an incident
list to count for itself, which keeps the numbers correct as the dataset grows
and means no unauthorised row is shipped to a client just to be tallied.

Three audiences, one module, because they ask the same questions of different
slices of the same table:

    my_summary        incidents I reported          every role
    assigned_summary  work assigned to me           engineers only
    summary           the whole organisation        admins only

The personal dashboards are scoped in SQL by the caller's own id, taken from the
verified token. A scope is never read from the request, so no parameter can
widen one.

Buildings, floors and seats: incidents whose facility was later deleted keep NULL
references (ON DELETE SET NULL, Slice 5). They are grouped under
ARCHIVED_LOCATION_LABEL rather than dropped, so the figures always add up to the
total. The stored location_snapshot is deliberately not parsed — it is display
text describing where something was, not a reliable key.
"""

from typing import Any

from .. import db, security
from ..http import Request, ok
from .incidents import CATEGORIES, PRIORITIES, STATUS_CLOSED, STATUSES

#: Bucket for incidents whose building, floor or seat has since been deleted.
ARCHIVED_LOCATION_LABEL = "Archived / Removed Location"

#: Bucket for incidents that legitimately have no seat — a lift, a corridor, a
#: bathroom. Distinct from the label above, which means "it had one and it is
#: gone"; merging them would misreport a deletion as a shared space.
NO_SEAT_LABEL = "Shared / No Specific Seat"

#: Bucket for incidents nobody is working on yet.
UNASSIGNED_LABEL = "Unassigned"

#: How far back the recurring-problem and impact analysis looks.
OPERATIONAL_WINDOW_DAYS = 30

#: Reports of one underlying problem before it counts as recurring.
RECURRING_THRESHOLD = 3

#: Illustrative hourly cost of a problem going unresolved, by priority.
#:
#: NOT an accounting figure — see the disclaimer the UI carries. It exists to
#: rank problems by how much attention they deserve, not to be put in a ledger.
#: Keys must match PRIORITIES exactly; a test asserts they do, so adding a
#: priority without a rate here fails loudly rather than silently costing £0.
PRIORITY_HOURLY_RATES = {"LOW": 10, "MEDIUM": 25, "HIGH": 50}

# Ranks the priorities so a group of duplicate reports can take the highest one.
# Kept as SQL because the grouping happens in the database.
_PRIORITY_RANK_SQL = "CASE i.priority WHEN 'HIGH' THEN 3 WHEN 'MEDIUM' THEN 2 ELSE 1 END"
_RANK_TO_PRIORITY = {3: "HIGH", 2: "MEDIUM", 1: "LOW"}

# "Active" means an engineer may still have to do something, so anything that is
# not CLOSED counts — including RESOLVED, which is awaiting admin review and can
# be sent back. Used for engineer workload.


def _counts_by(column: str, scope_sql: str, scope_params: list[Any]) -> dict[str, int]:
    """Count incidents grouped by one column, within a scope.

    Args:
        column: A column name. Never taken from user input — every call site
            passes a literal, so no request value reaches the SQL text.
        scope_sql: The restriction deciding whose incidents are counted.
    """
    where = f" WHERE {scope_sql}" if scope_sql else ""
    rows = db.query_all(
        f"SELECT {column} AS key, COUNT(*) AS n FROM incidents{where} GROUP BY {column}",
        tuple(scope_params),
    )
    return {row["key"]: row["n"] for row in rows}


def _fill(counts: dict[str, int], keys: tuple[str, ...]) -> dict[str, int]:
    """Zero-fill a breakdown so the dashboard renders a stable set of cards
    instead of rows appearing and disappearing as the data changes."""
    return {key: counts.get(key, 0) for key in keys}


def _core_counts(scope_sql: str, scope_params: list[Any]) -> dict[str, Any]:
    """Total plus the status and priority breakdowns every dashboard shows."""
    where = f" WHERE {scope_sql}" if scope_sql else ""
    total = db.query_one(
        f"SELECT COUNT(*) AS n FROM incidents{where}", tuple(scope_params)
    )["n"]

    return {
        "total": total,
        "by_status": _fill(_counts_by("status", scope_sql, scope_params), STATUSES),
        "by_priority": _fill(_counts_by("priority", scope_sql, scope_params), PRIORITIES),
    }


def my_summary(request: Request) -> dict[str, Any]:
    """Dashboard for the signed-in reporter: only incidents they raised.

    Available to every role — an engineer or admin who reports a broken tap sees
    it here like anyone else.
    """
    counts = _core_counts("created_by = %s", [request.user["id"]])
    counts["by_category"] = _fill(
        _counts_by("category", "created_by = %s", [request.user["id"]]), CATEGORIES
    )
    return ok(counts)


def assigned_summary(request: Request) -> dict[str, Any]:
    """Dashboard for an engineer's own queue: only work assigned to them.

    Restricted to ENGINEER by the route table, and scoped to the caller's id
    here, so one engineer cannot read another's workload.
    """
    counts = _core_counts("assignee_id = %s", [request.user["id"]])
    counts["by_category"] = _fill(
        _counts_by("category", "assignee_id = %s", [request.user["id"]]), CATEGORIES
    )
    return ok(counts)


def _location_breakdown(name_sql: str, join_sql: str, fallback: str) -> list[dict[str, Any]]:
    """Count incidents grouped by a facility level, busiest first.

    LEFT JOIN so detached incidents survive the grouping; an inner join would
    silently drop them and the figures would no longer sum to the total.
    """
    rows = db.query_all(
        f"""
        SELECT {name_sql} AS name, COUNT(*) AS n
        FROM incidents i
        {join_sql}
        GROUP BY {name_sql}
        ORDER BY COUNT(*) DESC, {name_sql}
        """
    )
    return [{"label": row["name"] or fallback, "count": row["n"]} for row in rows]


def _lifecycle_averages() -> dict[str, float | None]:
    """Average seconds from report to each milestone, across all incidents.

    Averaged in PostgreSQL rather than the browser: the client is never sent the
    timestamps, and an average of the rows a page happens to show is not the
    average of the data.

    AVG ignores NULLs, so each figure covers only the incidents that actually
    reached that milestone — an unassigned incident does not drag the
    time-to-assignment average towards zero. AVG over no rows returns NULL,
    which the caller renders as "not enough data" rather than as 0.
    """
    row = db.query_one(
        """
        SELECT
            AVG(EXTRACT(EPOCH FROM (acknowledged_at - created_at))) AS to_acknowledge,
            AVG(EXTRACT(EPOCH FROM (assigned_at     - created_at))) AS to_assign,
            AVG(EXTRACT(EPOCH FROM (resolved_at     - created_at))) AS to_resolve,
            AVG(EXTRACT(EPOCH FROM (closed_at       - created_at))) AS to_close,
            COUNT(acknowledged_at) AS acknowledged_count,
            COUNT(assigned_at)     AS assigned_count,
            COUNT(resolved_at)     AS resolved_count,
            COUNT(closed_at)       AS closed_count
        FROM incidents
        """
    )

    return {
        "seconds_to_acknowledge": _seconds(row["to_acknowledge"]),
        "seconds_to_assign": _seconds(row["to_assign"]),
        "seconds_to_resolve": _seconds(row["to_resolve"]),
        "seconds_to_close": _seconds(row["to_close"]),
        "acknowledged_count": row["acknowledged_count"],
        "assigned_count": row["assigned_count"],
        "resolved_count": row["resolved_count"],
        "closed_count": row["closed_count"],
    }


def _seconds(value: Any) -> float | None:
    """AVG returns Decimal or None; JSON wants a plain number or null."""
    return None if value is None else float(value)


def _engineer_workload() -> list[dict[str, Any]]:
    """Every engineer with their availability and how much live work they hold.

    LEFT JOIN so an engineer with nothing to do still appears — an empty queue
    is exactly what "who is free?" is asking about.
    """
    rows = db.query_all(
        """
        SELECT
            u.id, u.full_name, u.email, u.is_available,
            COUNT(i.id) FILTER (WHERE i.status <> %s) AS active_count,
            COUNT(i.id) AS total_count
        FROM users u
        LEFT JOIN incidents i ON i.assignee_id = u.id
        WHERE u.role = %s AND u.is_active = TRUE
        GROUP BY u.id, u.full_name, u.email, u.is_available
        ORDER BY COUNT(i.id) FILTER (WHERE i.status <> %s) DESC, u.full_name
        """,
        (STATUS_CLOSED, security.ROLE_ENGINEER, STATUS_CLOSED),
    )
    return rows


def _assignee_breakdown() -> list[dict[str, Any]]:
    """Incidents per assignee, including an explicit Unassigned bucket.

    Counts every incident rather than only active ones, so this reconciles
    against the headline total the way the other breakdowns do.
    """
    rows = db.query_all(
        """
        SELECT assignee.full_name AS name, COUNT(*) AS n
        FROM incidents i
        LEFT JOIN users assignee ON assignee.id = i.assignee_id
        GROUP BY assignee.full_name
        ORDER BY COUNT(*) DESC, assignee.full_name
        """
    )
    return [{"label": row["name"] or UNASSIGNED_LABEL, "count": row["n"]} for row in rows]


def summary(request: Request) -> dict[str, Any]:
    """The organisation-wide dashboard. Facility Admin only, enforced by the route table."""
    counts = _core_counts("", [])

    escalated = db.query_one(
        "SELECT COUNT(*) AS n FROM incidents WHERE escalation_requested"
    )["n"]

    return ok(
        {
            **counts,
            "by_category": _fill(_counts_by("category", "", []), CATEGORIES),
            "by_building": _location_breakdown(
                "building.name",
                "LEFT JOIN buildings building ON building.id = i.building_id",
                ARCHIVED_LOCATION_LABEL,
            ),
            # Floors are named per building ("Floor 1" exists everywhere), so the
            # label carries its building or the breakdown would merge unrelated
            # floors into one meaningless row.
            "by_floor": _location_breakdown(
                "(building.name || ' > ' || floor.name)",
                """
                LEFT JOIN floors floor ON floor.id = i.floor_id
                LEFT JOIN buildings building ON building.id = floor.building_id
                """,
                ARCHIVED_LOCATION_LABEL,
            ),
            # Seats need the same qualification, and additionally separate
            # "no seat applies" from "the seat was deleted".
            "by_seat": _seat_breakdown(),
            "by_assignee": _assignee_breakdown(),
            "engineers": _engineer_workload(),
            "lifecycle": _lifecycle_averages(),
            "escalations_open": escalated,
            # Reports collapsed into underlying problems. Deliberately separate
            # from every count above, which stays per incident.
            "operational": _operational_insights(),
        }
    )


def _underlying_problems() -> list[dict[str, Any]]:
    """Collapse recent incident reports into the underlying problems they describe.

    THE DISTINCTION THIS EXISTS FOR: three people reporting one broken lift are
    three incidents and one problem. The incident counts elsewhere in this module
    stay at three — that is how many tickets there are — but a problem that costs
    the business time costs it once, so impact is measured per problem.

    Grouping key: category plus the structured location (building, floor and
    seat ids). location_snapshot is deliberately not parsed; it is display text
    describing where something was, not a key, and two people can describe one
    place differently.

    An incident with no structured location — its facility was deleted, or it
    predates Slice 5 — becomes a group of its own. Without a location there is
    no evidence two such reports are the same problem, and merging them on
    category alone would silently discount unrelated work. That is what the
    ``CASE WHEN i.building_id IS NULL THEN i.id END`` term does: a real location
    contributes a constant NULL and the rows collapse, a missing one contributes
    the incident's own id and the row stands alone.

    Timing, per problem:
        started_at  earliest report — the problem began when someone first hit it
        ended_at    latest resolved/closed among its reports; the problem is only
                    over once the last ticket for it is
        is_active   any report still open, in progress or blocked
    """
    return db.query_all(
        f"""
        SELECT
            i.category                       AS category,
            building.name                    AS building_name,
            floor.name                       AS floor_name,
            seat.code                        AS seat_code,
            COUNT(*)                         AS report_count,
            MIN(i.created_at)                AS started_at,
            MAX(COALESCE(i.resolved_at, i.closed_at, i.updated_at)) AS ended_at,
            bool_or(i.status NOT IN ('RESOLVED', 'CLOSED')) AS is_active,
            MAX({_PRIORITY_RANK_SQL})        AS priority_rank,
            -- Seconds the problem has been, or was, unresolved. now() for one
            -- still running; GREATEST guards against a clock skew producing a
            -- negative duration.
            GREATEST(
                0,
                EXTRACT(EPOCH FROM (
                    CASE
                        WHEN bool_or(i.status NOT IN ('RESOLVED', 'CLOSED')) THEN now()
                        ELSE COALESCE(
                            MAX(COALESCE(i.resolved_at, i.closed_at, i.updated_at)),
                            now()
                        )
                    END - MIN(i.created_at)
                ))
            ) AS unresolved_seconds
        FROM incidents i
        LEFT JOIN buildings building ON building.id = i.building_id
        LEFT JOIN floors floor ON floor.id = i.floor_id
        LEFT JOIN seats seat ON seat.id = i.seat_id
        WHERE i.created_at >= now() - make_interval(days => %s)
        GROUP BY
            i.category,
            i.building_id, i.floor_id, i.seat_id,
            CASE WHEN i.building_id IS NULL THEN i.id END,
            building.name, floor.name, seat.code
        ORDER BY COUNT(*) DESC, MIN(i.created_at)
        """,
        (OPERATIONAL_WINDOW_DAYS,),
    )


def _problem_location(row: dict[str, Any]) -> str:
    """The most specific structured location available, as a readable path."""
    parts = [row["building_name"], row["floor_name"], row["seat_code"]]
    return " > ".join(part for part in parts if part) or ARCHIVED_LOCATION_LABEL


def _operational_insights() -> dict[str, Any]:
    """Recurring problems and an illustrative cost of leaving them unresolved.

    Each underlying problem is charged once, at the rate of the highest priority
    among its reports — so duplicate reports cannot multiply the estimate, and a
    problem somebody marked urgent is not understated because others filed it as
    routine.

    The rates are applied here rather than in SQL so they stay a visible product
    constant, and in the browser not at all: the figures arrive already totalled.
    """
    problems = _underlying_problems()

    estimated = 0.0
    active = 0.0
    by_priority = {priority: 0.0 for priority in PRIORITIES}
    recurring: list[dict[str, Any]] = []

    for row in problems:
        priority = _RANK_TO_PRIORITY[row["priority_rank"]]
        hours = float(row["unresolved_seconds"]) / 3600.0
        impact = round(hours * PRIORITY_HOURLY_RATES[priority], 2)

        estimated += impact
        by_priority[priority] += impact
        if row["is_active"]:
            active += impact

        if row["report_count"] >= RECURRING_THRESHOLD:
            recurring.append(
                {
                    "location": _problem_location(row),
                    "category": row["category"],
                    "reports": row["report_count"],
                    "priority": priority,
                    "is_active": row["is_active"],
                    "estimated_impact": impact,
                }
            )

    return {
        "window_days": OPERATIONAL_WINDOW_DAYS,
        "recurring_threshold": RECURRING_THRESHOLD,
        "hourly_rates": PRIORITY_HOURLY_RATES,
        "problem_count": len(problems),
        "recurring_count": len(recurring),
        "recurring_problems": recurring,
        # Both totals are sums of the same already-rounded per-problem amounts,
        # which is what makes the priority table reconcile with the headline
        # exactly rather than drifting by a penny per problem.
        "estimated_impact": round(estimated, 2),
        "active_impact": round(active, 2),
        "impact_by_priority": {
            priority: round(amount, 2) for priority, amount in by_priority.items()
        },
    }


def _seat_breakdown() -> list[dict[str, Any]]:
    """Counts per seat, with everything seatless in one bucket.

    Most incidents genuinely have no seat — a lift, a corridor, a bathroom — and
    a seat deleted afterwards also leaves seat_id NULL. The two are
    indistinguishable without parsing location_snapshot, which is display text
    rather than a key, so both are reported as NO_SEAT_LABEL. Deletions are rare
    and the building and floor breakdowns above still place those incidents.
    """
    rows = db.query_all(
        """
        SELECT
            CASE
                WHEN i.seat_id IS NULL THEN NULL
                ELSE building.name || ' > ' || floor.name || ' > ' || seat.code
            END AS name,
            COUNT(*) AS n
        FROM incidents i
        LEFT JOIN seats seat ON seat.id = i.seat_id
        LEFT JOIN floors floor ON floor.id = seat.floor_id
        LEFT JOIN buildings building ON building.id = floor.building_id
        GROUP BY 1
        ORDER BY COUNT(*) DESC, 1
        """
    )
    return [{"label": row["name"] or NO_SEAT_LABEL, "count": row["n"]} for row in rows]
