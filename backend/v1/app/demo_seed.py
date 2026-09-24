"""Seeding and removal of the demo dataset.

This is an operator tool, not part of the application. Nothing here runs on a
normal request: the only ways in are ``python -m app.demo_seed`` on a machine
that can reach the database, and a direct Lambda invocation carrying the private
marker below. See :func:`classify_event` for why an HTTP caller can never reach
it.

HOW ROWS ARE CREATED. Every building, floor, seat, account, incident, comment,
assignment, status change and escalation is created by calling
``router.dispatch`` with a real signed token — the same function the Lambda
handler calls. Route matching, authentication, the role gate and each handler's
own validation all run, so a seeded row cannot exist in a state the API would
have refused. The seeder holds no special powers inside the application; it is
simply a very fast user.

THE ONE EXCEPTION, AND WHY. Lifecycle timestamps are stamped by the database
with ``now()`` at the moment each endpoint runs, and no endpoint accepts a
historical date — correctly, since letting a client choose when something
happened would make every metric forgeable. A demo therefore cannot obtain
thirty days of history through the API without waiting thirty days. After
everything has been created through the API, :func:`_backdate` rewrites the
timestamp columns of the rows this seeder created, and only those rows, in one
transaction. It changes when things happened, never what happened: statuses,
assignments, authorship and text are exactly what the handlers produced, and
``demo_data.validate_plan`` has already checked that every timeline is ordered
and that live incidents carry no completion timestamps.

WHICH ROWS ARE OURS. A manifest in the existing ``app_config`` table records the
primary key of every row the seeder created, so removal is by identity rather
than by guesswork — no pattern matching against names that a real record might
also match, and no new schema. It is written after each phase, so a run that
fails halfway still leaves a complete record of what to remove. Rows that
already existed are adopted rather than recreated and are deliberately left out
of the manifest, which is what stops cleanup deleting something it did not make.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from . import db, demo_data, security
from .domains.incidents import (
    STATUS_BLOCKED,
    STATUS_CLOSED,
    STATUS_IN_PROGRESS,
    STATUS_OPEN,
    STATUS_RESOLVED,
)
from .errors import AppError, ConflictError
from .http import Request
from .router import dispatch

logger = logging.getLogger(__name__)

#: Where the record of what we created lives. ``app_config`` already exists for
#: settings shared by every Lambda copy, which is exactly what this is.
MANIFEST_KEY = "demo_seed_manifest"
MANIFEST_VERSION = 1

#: The top-level event key and the exact marker a direct invocation must carry.
#: Both are required; neither is guessable from the public API surface, and a
#: Function URL request cannot produce either — see classify_event.
DIRECT_INVOKE_KEY = "demo_seed"
DIRECT_INVOKE_MARKER = "acme.facility.demo-seed.v1"

ACTIONS = ("seed", "clean", "status")

#: Keys AWS puts on an HTTP event, from Function URLs and from both API Gateway
#: payload formats. If any of these is present the event came from the web, and
#: this module refuses to look at it.
_HTTP_EVENT_KEYS = frozenset(
    {
        "body",
        "cookies",
        "headers",
        "httpMethod",
        "isBase64Encoded",
        "multiValueHeaders",
        "multiValueQueryStringParameters",
        "path",
        "pathParameters",
        "queryStringParameters",
        "rawPath",
        "rawQueryString",
        "requestContext",
        "resource",
        "routeKey",
        "stageVariables",
        "version",
    }
)

# Event classifications returned by classify_event.
EVENT_HTTP = "http"
EVENT_DIRECT = "direct"
EVENT_AMBIGUOUS = "ambiguous"


class SeedError(Exception):
    """Something stopped the seeder that the operator has to fix."""


# ---------------------------------------------------------------------------
# Event classification — the security boundary for direct invocation
# ---------------------------------------------------------------------------
def classify_event(event: Any) -> str:
    """Decide whether an event is an HTTP request or a direct seed invocation.

    THIS IS THE CONTROL THAT KEEPS SEEDING OFF THE PUBLIC INTERNET, so it is
    written to be read rather than to be short.

    A Lambda Function URL — the only public entry point this service has —
    always builds its event from the HTTP request, and that event always carries
    ``requestContext``, ``headers`` and ``rawPath``. A caller cannot suppress
    them: they are added by the Lambda service after the request is received,
    not copied from anything the caller sends. A JSON body is delivered as the
    ``body`` *string*, never merged into the top level of the event, so a caller
    who posts ``{"demo_seed": ...}`` produces an event whose top level still has
    no ``demo_seed`` key at all.

    So the two populations are disjoint by construction, and this function
    refuses to guess between them:

    * any HTTP key present, and no seed marker  -> an ordinary request
    * the seed marker present, and no HTTP key  -> a direct invocation
    * both present                              -> ambiguous, refused outright

    The third case cannot arise from either real source. It is refused rather
    than resolved because the safe reading of a crafted event is that somebody
    is trying to reach the seeder through the front door.

    Authorisation for the direct path is AWS IAM: invoking a Lambda directly
    requires ``lambda:InvokeFunction`` on this function, which only the account
    owner holds. The marker is not a secret and is not treated as one — it
    distinguishes a deliberate call from a stray one.
    """
    if not isinstance(event, dict):
        return EVENT_HTTP

    looks_http = bool(_HTTP_EVENT_KEYS & set(event))
    payload = event.get(DIRECT_INVOKE_KEY)
    carries_marker = (
        isinstance(payload, dict) and payload.get("marker") == DIRECT_INVOKE_MARKER
    )

    if carries_marker and looks_http:
        return EVENT_AMBIGUOUS
    if carries_marker:
        return EVENT_DIRECT
    # An event carrying the key but the wrong marker is not a seed invocation.
    # It falls through to the HTTP path, where it will fail as a malformed
    # request — which is the correct answer for a malformed event.
    return EVENT_HTTP


def handle_direct_invoke(event: dict[str, Any]) -> dict[str, Any]:
    """Run a seed action for an event ``classify_event`` accepted.

    Returns a plain dictionary rather than an HTTP response: a direct
    invocation has no status code, and shaping it like one would suggest this
    is reachable over the web.
    """
    payload = event[DIRECT_INVOKE_KEY]
    action = payload.get("action")

    if action not in ACTIONS:
        return {"ok": False, "error": f"action must be one of {', '.join(ACTIONS)}"}

    try:
        return {"ok": True, "action": action, "result": run(action, payload.get("password"))}
    except (SeedError, AppError) as exc:
        logger.error("Demo seed action %s failed: %s", action, exc)
        return {"ok": False, "action": action, "error": str(exc)}


# ---------------------------------------------------------------------------
# Calling the application
# ---------------------------------------------------------------------------
def _call(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: Any = None,
    expect: tuple[int, ...] = (200, 201, 204),
) -> Any:
    """Make one authenticated request through the real router.

    Goes through ``dispatch`` rather than calling a handler, so the route's
    declared role set is enforced exactly as it is for a browser.
    """
    headers = {"authorization": f"Bearer {token}"} if token else {}
    request = Request(method=method, path=path, headers=headers, body=body)

    response = dispatch(request)
    status = response["statusCode"]

    if status not in expect:
        raise SeedError(f"{method} {path} returned {status}: {response['body']}")

    return json.loads(response["body"]) if response["body"] else None


def _admin_token() -> str:
    """A token for an existing Facility Admin.

    Minted rather than obtained by signing in, so the seeder never needs an
    administrator's password and none has to be supplied to it. This is not an
    escalation: the token is an ordinary signed token for an account that
    already holds the role, and ``require_roles`` still checks it on every call
    below. Anyone able to run this already has direct database access.
    """
    admin = db.query_one(
        "SELECT id, email, role FROM users "
        "WHERE role = %s AND is_active = TRUE "
        "ORDER BY (email = %s) DESC, id LIMIT 1",
        (security.ROLE_FACILITY_ADMIN, security.SEED_ADMIN_EMAIL),
    )

    if admin is None:
        raise SeedError(
            "No active Facility Admin account exists, so the demo dataset cannot be "
            "created. Start the application once with BOOTSTRAP_ADMIN_PASSWORD set "
            "so the bootstrap administrator is created."
        )

    return security.create_access_token(admin)


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------
def _empty_manifest() -> dict[str, Any]:
    return {
        "version": MANIFEST_VERSION,
        "seeded_at": datetime.now(timezone.utc).isoformat(),
        "users": [],
        "buildings": [],
        "floors": [],
        "seats": [],
        "incidents": [],
        "comments": [],
    }


def load_manifest() -> dict[str, Any] | None:
    """The record of the current demo dataset, or None if there is none."""
    row = db.query_one("SELECT value FROM app_config WHERE key = %s", (MANIFEST_KEY,))
    if row is None:
        return None
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        raise SeedError(
            f"The demo manifest in app_config ({MANIFEST_KEY}) is not readable JSON. "
            "Remove that row by hand to reset the seeder."
        )


def _save_manifest(manifest: dict[str, Any]) -> None:
    """Write the manifest out. Called after each phase so an interrupted run
    still leaves a complete record of what needs removing."""
    db.execute(
        """
        INSERT INTO app_config (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
        """,
        (MANIFEST_KEY, json.dumps(manifest)),
    )


def _clear_manifest() -> None:
    db.execute("DELETE FROM app_config WHERE key = %s", (MANIFEST_KEY,))


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------
def _seed_facilities(manifest: dict[str, Any], admin: str, plan) -> dict[str, Any]:
    """Create buildings, floors and seats, adopting any that already exist.

    Adoption matters for safety rather than convenience: a building that was
    already there is somebody else's record, so it is used but never written to
    the manifest, and cleanup will therefore never remove it.
    """
    existing_buildings = {
        row["name"]: row["id"] for row in _call("GET", "/buildings", token=admin)["buildings"]
    }

    lookup: dict[str, Any] = {}

    for building in plan.buildings:
        name = building["name"]
        if name in existing_buildings:
            building_id = existing_buildings[name]
        else:
            created = _call(
                "POST",
                "/buildings",
                token=admin,
                body={"name": name, "address": building["address"]},
            )["building"]
            building_id = created["id"]
            manifest["buildings"].append(building_id)

        floors: dict[str, Any] = {}
        existing_floors = {
            row["name"]: row["id"]
            for row in _call("GET", f"/buildings/{building_id}/floors", token=admin)["floors"]
        }

        for floor in building["floors"]:
            if floor["name"] in existing_floors:
                floor_id = existing_floors[floor["name"]]
            else:
                floor_id = _call(
                    "POST",
                    "/floors",
                    token=admin,
                    body={"building_id": building_id, "name": floor["name"]},
                )["floor"]["id"]
                manifest["floors"].append(floor_id)

            existing_seats = {
                row["code"]: row["id"]
                for row in _call("GET", f"/floors/{floor_id}/seats", token=admin)["seats"]
            }
            seats: dict[str, int] = {}
            for code in floor["seats"]:
                if code in existing_seats:
                    seats[code] = existing_seats[code]
                else:
                    seat_id = _call(
                        "POST", "/seats", token=admin, body={"floor_id": floor_id, "code": code}
                    )["seat"]["id"]
                    manifest["seats"].append(seat_id)
                    seats[code] = seat_id

            floors[floor["name"]] = {"id": floor_id, "seats": seats}

        lookup[name] = {"id": building_id, "floors": floors}

    _save_manifest(manifest)
    return lookup


def _register(manifest: dict[str, Any], person: dict[str, str], password: str) -> dict[str, Any]:
    """Create one account, or adopt it if the address is already taken."""
    try:
        payload = _call(
            "POST",
            "/auth/register",
            body={
                "full_name": person["full_name"],
                "email": person["email"],
                "password": password,
            },
            expect=(201,),
        )
        manifest["users"].append(payload["user"]["id"])
        return {"id": payload["user"]["id"], "token": payload["token"]}
    except ConflictError:
        existing = db.query_one(
            "SELECT id, email, role FROM users WHERE email = %s", (person["email"].lower(),)
        )
        if existing is None:  # pragma: no cover - only if the row vanished mid-run
            raise SeedError(f"Could not create or find the account {person['email']}")
        # Adopted, so deliberately not recorded in the manifest.
        return {"id": existing["id"], "token": security.create_access_token(existing)}


def _seed_people(manifest: dict[str, Any], admin: str, plan, password: str) -> dict[str, Any]:
    """Create the demo accounts and promote the engineers.

    Registration always produces an EMPLOYEE — the endpoint has no way to ask
    for anything else — so engineers are promoted afterwards through the admin
    role endpoint, which is the same path a real Facility Admin would take.

    The token issued at registration keeps working after the promotion because
    ``authenticate_request`` re-reads the role from the database rather than
    trusting the one inside the token.
    """
    employees = [_register(manifest, person, password) for person in plan.employees]
    engineers = [_register(manifest, person, password) for person in plan.engineers]

    for engineer in engineers:
        _call(
            "PATCH",
            f"/users/{engineer['id']}/role",
            token=admin,
            body={"role": security.ROLE_ENGINEER},
        )

    _save_manifest(manifest)
    return {"employees": employees, "engineers": engineers}


def _seed_incidents(manifest, admin, plan, people, facilities) -> None:
    """Create every incident and walk it to its final status through the API.

    The order is the order a real ticket goes through, and it has to be: the API
    refuses an escalation on a finished incident and refuses a comment on a
    closed one, so both happen while the incident is still live.
    """
    employees = people["employees"]
    engineers = people["engineers"]

    for spec in plan.incidents:
        reporter = employees[spec.reporter]
        place = facilities[spec.building]
        floor = place["floors"][spec.floor]
        seat_id = floor["seats"][spec.seat] if spec.seat else None

        incident = _call(
            "POST",
            "/incidents",
            token=reporter["token"],
            body={
                "title": spec.title,
                "description": spec.description,
                "category": spec.category,
                "priority": spec.priority,
                "building_id": place["id"],
                "floor_id": floor["id"],
                "seat_id": seat_id,
            },
            expect=(201,),
        )["incident"]

        incident_id = incident["id"]
        manifest["incidents"].append(incident_id)

        assigned = spec.engineer is not None and spec.engineer >= 0
        engineer = engineers[spec.engineer] if assigned else None

        if assigned:
            _call(
                "PATCH",
                f"/incidents/{incident_id}",
                token=admin,
                body={"assignee_id": engineer["id"]},
            )

        # While the incident is still OPEN, which is the only window the
        # escalation endpoint accepts for some of these statuses.
        if spec.escalation_reason:
            _call(
                "POST",
                f"/incidents/{incident_id}/escalation",
                token=reporter["token"],
                body={"reason": spec.escalation_reason},
                expect=(200, 201),
            )

        for comment in spec.comments:
            author_token = {
                "reporter": reporter["token"],
                "engineer": engineer["token"] if engineer else reporter["token"],
                "admin": admin,
            }[comment.author]
            created = _call(
                "POST",
                f"/incidents/{incident_id}/comments",
                token=author_token,
                body={"body": comment.body},
                expect=(201,),
            )["comment"]
            manifest["comments"].append(created["id"])

        _advance_status(admin, engineer, incident_id, spec)

    _save_manifest(manifest)


def _advance_status(admin: str, engineer: dict | None, incident_id: int, spec) -> None:
    """Walk one incident from OPEN to its planned status, one real PATCH at a time.

    Engineers make the working transitions on their own assigned incidents and
    an admin closes, which is the division the application enforces — an
    engineer asking for CLOSED is refused. Doing it this way rather than writing
    the status column means the seeded data cannot contain a transition the
    application would not allow.
    """
    if spec.status == STATUS_OPEN or engineer is None:
        return

    worker = engineer["token"]

    _call("PATCH", f"/incidents/{incident_id}", token=worker, body={"status": STATUS_IN_PROGRESS})

    if spec.status == STATUS_IN_PROGRESS:
        return

    if spec.status == STATUS_BLOCKED:
        _call(
            "PATCH",
            f"/incidents/{incident_id}",
            token=worker,
            body={"status": STATUS_BLOCKED, "blocked_reason": spec.blocked_reason},
        )
        return

    _call("PATCH", f"/incidents/{incident_id}", token=worker, body={"status": STATUS_RESOLVED})

    if spec.status == STATUS_CLOSED:
        # Only an admin may accept the work as finished.
        _call("PATCH", f"/incidents/{incident_id}", token=admin, body={"status": STATUS_CLOSED})


def _set_availability(admin: str, plan, people) -> None:
    """Mark some engineers unavailable.

    Deliberately last. An unavailable engineer may not be given *new* work, so
    doing this before assignment would make those assignments fail — and leaving
    their existing queue intact is precisely the behaviour the demo is showing.
    """
    for index in sorted(plan.unavailable_engineers):
        engineer = people["engineers"][index]
        _call(
            "PATCH",
            f"/users/{engineer['id']}/availability",
            token=admin,
            body={"is_available": False},
        )


# ---------------------------------------------------------------------------
# Backdating
# ---------------------------------------------------------------------------
_INCIDENT_TIME_COLUMNS = (
    "created_at",
    "acknowledged_at",
    "assigned_at",
    "resolved_at",
    "closed_at",
    "escalated_at",
    "updated_at",
)


def _interval(seconds: int | None) -> tuple[str, list[Any]]:
    """SQL for a timestamp that many seconds before now, or NULL.

    Computed by PostgreSQL from its own clock rather than sent as an absolute
    time, so the dataset is anchored to the database and a skewed laptop clock
    cannot shift the history.
    """
    if seconds is None:
        return "NULL", []
    return "now() - make_interval(secs => %s)", [int(seconds)]


def _backdate(plan, incident_ids: list[int], comment_ids: list[int]) -> None:
    """Rewrite the lifecycle timestamps of the rows we just created.

    One transaction, scoped by primary key to this seeder's own rows. The
    column names come from the tuple above, never from data, so nothing here
    can become SQL by accident.
    """
    if not incident_ids:
        return

    comment_cursor = 0

    with db.transaction() as cur:
        for spec, incident_id in zip(plan.incidents, incident_ids):
            timeline = spec.timeline
            values = (
                timeline.created,
                timeline.acknowledged,
                timeline.assigned,
                timeline.resolved,
                timeline.closed,
                timeline.escalated,
                timeline.updated,
            )

            assignments = []
            params: list[Any] = []
            for column, seconds in zip(_INCIDENT_TIME_COLUMNS, values):
                fragment, fragment_params = _interval(seconds)
                assignments.append(f"{column} = {fragment}")
                params.extend(fragment_params)

            params.append(incident_id)
            cur.execute(
                f"UPDATE incidents SET {', '.join(assignments)} WHERE id = %s", tuple(params)
            )

            for comment in spec.comments:
                if comment_cursor >= len(comment_ids):
                    break
                cur.execute(
                    "UPDATE incident_comments "
                    "SET created_at = now() - make_interval(secs => %s) WHERE id = %s",
                    (int(comment.seconds_ago), comment_ids[comment_cursor]),
                )
                comment_cursor += 1


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
def _in_use_by_others(cur, column: str, table: str, ids: list[int], demo_incident_ids: list[int]):
    """Ids still referenced by rows this seeder did not create.

    The guard that makes cleanup safe for facilities: a building the seeder made
    might since have had a real incident reported against it, and that incident's
    ``building_id`` is ON DELETE SET NULL — removing the building would quietly
    detach somebody's real record. Those ids are skipped and reported instead.
    """
    if not ids:
        return set()
    cur.execute(
        f"SELECT DISTINCT {column} AS id FROM {table} "
        f"WHERE {column} = ANY(%s) AND NOT (id = ANY(%s))",
        (ids, demo_incident_ids or [0]),
    )
    return {row["id"] for row in cur.fetchall() if row["id"] is not None}


def clean() -> dict[str, Any]:
    """Remove every row recorded in the manifest, and nothing else."""
    manifest = load_manifest()
    if manifest is None:
        return {"found": False, "removed": {}, "skipped": {}}

    incidents = manifest.get("incidents", [])
    users = manifest.get("users", [])
    buildings = manifest.get("buildings", [])
    floors = manifest.get("floors", [])
    seats = manifest.get("seats", [])

    removed = {k: 0 for k in ("comments", "incidents", "users", "seats", "floors", "buildings")}
    skipped: dict[str, int] = {}

    with db.transaction() as cur:
        # Comments first: they reference both incidents and users.
        if incidents:
            cur.execute(
                "DELETE FROM incident_comments WHERE incident_id = ANY(%s)", (incidents,)
            )
            removed["comments"] += cur.rowcount
        if users:
            cur.execute("DELETE FROM incident_comments WHERE author_id = ANY(%s)", (users,))
            removed["comments"] += cur.rowcount

        if incidents:
            cur.execute("DELETE FROM incidents WHERE id = ANY(%s)", (incidents,))
            removed["incidents"] = cur.rowcount

        # Facilities, but only where no surviving incident still points at them.
        for key, ids, table_column in (
            ("seats", seats, "seat_id"),
            ("floors", floors, "floor_id"),
            ("buildings", buildings, "building_id"),
        ):
            if not ids:
                continue
            in_use = _in_use_by_others(cur, table_column, "incidents", ids, incidents)
            deletable = [i for i in ids if i not in in_use]
            if in_use:
                skipped[key] = len(in_use)
            if deletable:
                table = key
                cur.execute(f"DELETE FROM {table} WHERE id = ANY(%s)", (deletable,))
                removed[key] = cur.rowcount

        # Accounts last, and only those nothing else references. Incidents and
        # comments have no ON DELETE rule on their user columns on purpose —
        # history outlives an account — so a demo user who reported a real
        # incident is kept rather than forcing the deletion.
        if users:
            cur.execute(
                """
                SELECT DISTINCT u.id
                FROM users u
                WHERE u.id = ANY(%s)
                  AND (
                    EXISTS (SELECT 1 FROM incidents i
                             WHERE i.created_by = u.id OR i.assignee_id = u.id)
                    OR EXISTS (SELECT 1 FROM incident_comments c WHERE c.author_id = u.id)
                  )
                """,
                (users,),
            )
            still_referenced = {row["id"] for row in cur.fetchall()}
            deletable = [i for i in users if i not in still_referenced]
            if still_referenced:
                skipped["users"] = len(still_referenced)
            if deletable:
                cur.execute("DELETE FROM users WHERE id = ANY(%s)", (deletable,))
                removed["users"] = cur.rowcount

    _clear_manifest()

    return {"found": True, "removed": removed, "skipped": skipped}


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
def _summary(manifest: dict[str, Any]) -> dict[str, Any]:
    """Count what is actually in the database, not what the plan intended.

    Reading the rows back is what makes the printed summary evidence rather
    than a restatement of the generator's own arithmetic.
    """
    incidents = manifest.get("incidents", [])
    users = manifest.get("users", [])

    if not incidents:
        return {"incidents": 0}

    status_rows = db.query_all(
        "SELECT status, COUNT(*) AS n FROM incidents WHERE id = ANY(%s) GROUP BY status",
        (incidents,),
    )
    by_status = {row["status"]: row["n"] for row in status_rows}

    totals = db.query_one(
        """
        SELECT
          (SELECT COUNT(*) FROM incidents WHERE id = ANY(%s)) AS incidents,
          (SELECT COUNT(*) FROM incidents
            WHERE id = ANY(%s) AND escalation_requested) AS escalated,
          (SELECT COUNT(*) FROM incident_comments WHERE incident_id = ANY(%s)) AS comments,
          (SELECT COUNT(*) FROM users WHERE id = ANY(%s) AND role = 'ENGINEER') AS engineers,
          (SELECT COUNT(*) FROM users WHERE id = ANY(%s) AND role = 'EMPLOYEE') AS employees,
          (SELECT COUNT(*) FROM users
            WHERE id = ANY(%s) AND role = 'ENGINEER' AND NOT is_available) AS unavailable
        """,
        (incidents, incidents, incidents, users, users, users),
    )

    return {
        "buildings": len(manifest.get("buildings", [])),
        "floors": len(manifest.get("floors", [])),
        "seats": len(manifest.get("seats", [])),
        "employees": totals["employees"],
        "engineers": totals["engineers"],
        "unavailable_engineers": totals["unavailable"],
        "incidents": totals["incidents"],
        "by_status": {
            status: by_status.get(status, 0)
            for status in (
                STATUS_OPEN,
                STATUS_IN_PROGRESS,
                STATUS_BLOCKED,
                STATUS_RESOLVED,
                STATUS_CLOSED,
            )
        },
        "comments": totals["comments"],
        "escalated": totals["escalated"],
        "recurring_clusters": demo_data.recurring_cluster_count(),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def seed(password: str) -> dict[str, Any]:
    """Create the demo dataset, replacing any that is already there.

    Replacing rather than adding is what makes the script safe to run twice: a
    second run removes exactly what the first one made and rebuilds it, so the
    dataset stays the size it is supposed to be.
    """
    if not password or len(password) < 8:
        raise SeedError(
            "A demo account password of at least 8 characters must be supplied. "
            "The wrapper script generates and stores one; see bin/seed-demo-data.sh."
        )

    replaced = None
    if load_manifest() is not None:
        logger.info("An existing demo dataset was found; replacing it")
        replaced = clean()

    plan = demo_data.build_plan()
    manifest = _empty_manifest()
    _save_manifest(manifest)

    admin = _admin_token()

    facilities = _seed_facilities(manifest, admin, plan)
    people = _seed_people(manifest, admin, plan, password)
    _seed_incidents(manifest, admin, plan, people, facilities)
    _set_availability(admin, plan, people)

    _backdate(plan, manifest["incidents"], manifest["comments"])

    _save_manifest(manifest)

    summary = _summary(manifest)
    summary["replaced_previous"] = bool(replaced and replaced.get("found"))
    return summary


def status() -> dict[str, Any]:
    """Report whether a demo dataset is present, and what it contains."""
    manifest = load_manifest()
    if manifest is None:
        return {"present": False}
    return {"present": True, "seeded_at": manifest.get("seeded_at"), **_summary(manifest)}


def run(action: str, password: str | None = None) -> dict[str, Any]:
    """Dispatch one of the three actions. The single entry point for both the
    command line and a direct Lambda invocation."""
    if action == "seed":
        return seed(password or "")
    if action == "clean":
        return clean()
    if action == "status":
        return status()
    raise SeedError(f"Unknown action {action!r}; expected one of {', '.join(ACTIONS)}")


def main(argv: list[str] | None = None) -> int:
    """Command line for local use: ``python -m app.demo_seed seed``.

    The password is read from the environment rather than an argument, so it
    never appears in a process list or a shell history file.
    """
    import argparse
    import os

    from . import migrations

    parser = argparse.ArgumentParser(description="Seed or remove the ACME demo dataset.")
    parser.add_argument("action", choices=ACTIONS)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    # The schema has to exist before anything can be seeded into it. Running
    # migrations here means the seeder works against a fresh database without
    # having to start the application first.
    migrations.run_migrations()

    result = run(args.action, os.environ.get("DEMO_USER_PASSWORD"))
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
