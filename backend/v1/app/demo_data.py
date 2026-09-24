"""The demo dataset itself: what to create, and when each thing happened.

Pure data generation — nothing here touches the database or the API. Keeping
the plan separate from the execution means the shape of the dataset can be
inspected and asserted in tests without a database, and the seeder in
``demo_seed`` stays a short, readable loop.

Everything is generated from a fixed random seed, so two runs produce byte-for-byte
the same plan. That is what lets the seeder promise a deterministic dataset.

TIME IS EXPRESSED AS "SECONDS AGO", not as absolute timestamps. The seeder turns
each offset into ``now() - make_interval(secs => n)`` inside PostgreSQL, so the
dataset is anchored to the database's clock rather than the laptop's. A demo
seeded on Monday still reads as "the last 30 days" when it is opened on Friday
only if it is reseeded — the offsets are relative to the moment of seeding.

Two properties of the plan are load-bearing for the demo and are asserted by
``validate_plan``:

* Every incident falls inside ``OPERATIONAL_WINDOW_DAYS``, so Operational
  Insights sees the whole dataset.
* Exactly four groups reach ``RECURRING_THRESHOLD``. One-off incidents are
  generated with a cap of two per grouping key, so no accidental fifth cluster
  appears and the number on the dashboard is predictable.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from .domains.analytics import OPERATIONAL_WINDOW_DAYS, RECURRING_THRESHOLD
from .domains.incidents import (
    STATUS_BLOCKED,
    STATUS_CLOSED,
    STATUS_IN_PROGRESS,
    STATUS_OPEN,
    STATUS_RESOLVED,
)

#: Changing this changes the dataset. It is fixed so that "run it again and you
#: get the same demo" holds — useful when rehearsing a presentation.
RANDOM_SEED = 20260924

#: Local-part prefix on every demo account. The database CHECK constraint
#: requires an @acme.inc address, so the marker goes in front of the name rather
#: than in the domain. It is a backstop for cleanup, not the primary record —
#: see the manifest in demo_seed.
DEMO_EMAIL_PREFIX = "demo."

HOUR = 3600
DAY = 24 * HOUR

# Leave a margin at both ends: nothing is stamped in the future, and nothing
# falls outside the 30-day analytics window through rounding.
_NEWEST_SECONDS_AGO = 2 * HOUR
_OLDEST_SECONDS_AGO = 28 * DAY


# ---------------------------------------------------------------------------
# Facilities
# ---------------------------------------------------------------------------
#: Seat codes follow the building's initials and the floor number, which is how
#: a real estate team labels desks and makes the analytics readable at a glance.
FACILITIES: list[dict[str, Any]] = [
    {
        "name": "ACME Headquarters",
        "address": "1 Sterling Way, Manchester M1 4BT",
        "code": "HQ",
        "floors": [
            {"name": "Floor 1", "seats": 3},
            {"name": "Floor 2", "seats": 3},
            {"name": "Floor 3", "seats": 3},
            {"name": "Floor 4", "seats": 3},
        ],
    },
    {
        "name": "Innovation Center",
        "address": "14 Foundry Street, Manchester M4 1HW",
        "code": "IC",
        "floors": [
            {"name": "Floor 1", "seats": 3},
            {"name": "Floor 2", "seats": 3},
            {"name": "Floor 3", "seats": 2},
        ],
    },
    {
        "name": "Operations Center",
        "address": "Unit 7, Trafford Park, Manchester M17 1WA",
        "code": "OC",
        "floors": [
            {"name": "Ground Floor", "seats": 3},
            {"name": "Floor 1", "seats": 3},
            {"name": "Floor 2", "seats": 2},
        ],
    },
    {
        "name": "Research Building",
        "address": "3 Kelvin Court, Salford M50 2HF",
        "code": "RB",
        "floors": [
            {"name": "Floor 1", "seats": 3},
            {"name": "Floor 2", "seats": 2},
            {"name": "Floor 3", "seats": 2},
        ],
    },
    {
        "name": "Customer Support Center",
        "address": "22 Peel Road, Bolton BL1 2AX",
        "code": "CS",
        "floors": [
            {"name": "Floor 1", "seats": 3},
            {"name": "Floor 2", "seats": 2},
        ],
    },
]

#: How many incidents each building carries. Deliberately lopsided — a flat
#: distribution makes the "busiest building" chart useless as a demo.
BUILDING_WEIGHTS = {
    "ACME Headquarters": 34,
    "Innovation Center": 22,
    "Operations Center": 20,
    "Research Building": 14,
    "Customer Support Center": 10,
}


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------
ENGINEER_NAMES = [
    ("Priya Raman", "priya.raman"),
    ("Daniel Okafor", "daniel.okafor"),
    ("Marta Kowalski", "marta.kowalski"),
    ("Hiroshi Tanaka", "hiroshi.tanaka"),
    ("Aisha Bello", "aisha.bello"),
    ("Tomas Herrera", "tomas.herrera"),
    ("Lena Vogel", "lena.vogel"),
    ("Samuel Adeyemi", "samuel.adeyemi"),
    ("Nadia Farouk", "nadia.farouk"),
    ("Connor Walsh", "connor.walsh"),
]

EMPLOYEE_NAMES = [
    ("Elena Petrova", "elena.petrova"),
    ("Marcus Bennett", "marcus.bennett"),
    ("Yuki Nakamura", "yuki.nakamura"),
    ("Rachel Osei", "rachel.osei"),
    ("Ibrahim Haddad", "ibrahim.haddad"),
    ("Sophie Lambert", "sophie.lambert"),
    ("Andrei Popescu", "andrei.popescu"),
    ("Grace Mwangi", "grace.mwangi"),
]

#: Active (non-CLOSED) tickets each engineer should end up holding, by index
#: into ENGINEER_NAMES. Uneven on purpose: the workload panel is only worth
#: showing if somebody is visibly overloaded and somebody is visibly free.
ENGINEER_ACTIVE_TARGETS = [8, 7, 5, 5, 4, 4, 3, 3, 3, 0]

#: Engineers who are away. One of them is deliberately the busiest, which is
#: what demonstrates that going unavailable keeps the work already assigned.
UNAVAILABLE_ENGINEERS = {0, 5, 8}


# ---------------------------------------------------------------------------
# Incident text
# ---------------------------------------------------------------------------
#: Wording a real reporter would use — symptom first, no diagnosis. Each entry
#: is (title, description).
INCIDENT_TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "TECHNOLOGY": [
        ("Monitor loses signal intermittently", "The external monitor drops out every few minutes and comes back on its own."),
        ("Desk phone has no dial tone", "No dial tone since this morning. The handset light is on but calls will not connect."),
        ("Meeting room display will not connect", "The room screen does not pick up HDMI from any laptop we have tried."),
        ("Wi-Fi keeps dropping in this corner", "Connection drops roughly every ten minutes and reconnects on its own."),
        ("Docking station not charging laptop", "The dock passes through video but the laptop battery keeps draining."),
        ("Printer jams on every double-sided job", "Single-sided printing is fine. Duplex jams in the same place each time."),
        ("Badge reader rejects valid passes", "Several of us have had to be let in by reception this week."),
        ("Conference speakerphone crackles", "Callers say we sound broken up. The crackle is audible in the room too."),
        ("Second monitor not detected after update", "Only one screen is recognised since the machine restarted overnight."),
        ("Network port at desk appears dead", "No link light on the wall port. The same cable works at the next desk."),
    ],
    "ELECTRICAL": [
        ("Ceiling lights flickering", "The row of lights above the desks flickers continuously."),
        ("Power socket at desk is dead", "Nothing plugged into the left-hand socket receives power."),
        ("Circuit breaker tripped again", "Third time this month. It trips when the kettle and microwave run together."),
        ("Emergency light stuck on", "The emergency light by the stairwell has been lit constantly for days."),
        ("Extension lead sparking", "A visible spark when anything is plugged in. It has been unplugged for now."),
        ("Lighting sensor not triggering", "The motion sensor does not pick anyone up, so the area stays dark."),
    ],
    "PLUMBING": [
        ("Tap running continuously", "The hot tap in the kitchen will not shut off fully."),
        ("Toilet cistern overflowing", "Water is running constantly into the bowl and onto the floor."),
        ("Water cooler leaking", "A steady drip has soaked the mat underneath."),
        ("Blocked sink in the kitchen", "The sink drains very slowly and smells."),
        ("No hot water in the washroom", "Cold only, all day, on both taps."),
        ("Damp patch spreading on the ceiling", "A brown stain that has grown noticeably since last week."),
    ],
    "HVAC": [
        ("Area is far too warm", "Consistently uncomfortable through the afternoon regardless of the thermostat."),
        ("Air conditioning blowing warm air", "The unit runs but the air coming out is warm."),
        ("Heating will not turn off", "Radiators are on full even with the windows open."),
        ("Persistent draught near the windows", "Cold air comes through even when everything is shut."),
        ("Ventilation unit rattling", "A loud rattle from the ceiling unit, worse when it first starts."),
        ("Room never reaches set temperature", "The thermostat is set to twenty-one but the room sits closer to twenty-six."),
    ],
    "FURNITURE": [
        ("Office chair gas lift failed", "The seat sinks to its lowest position as soon as anyone sits down."),
        ("Desk wobbles badly", "The frame rocks whenever anything is typed."),
        ("Drawer unit will not lock", "The lock turns but does not engage, so the drawers cannot be secured."),
        ("Meeting room chair broken", "One of the chairs has a cracked back and is not safe to use."),
        ("Sit-stand desk stuck at one height", "The controller beeps but the desk does not move."),
        ("Cupboard door hanging off", "The top hinge has pulled out of the frame."),
    ],
    "OTHER": [
        ("Bin area needs attention", "Overflowing since the weekend and beginning to smell."),
        ("Entrance door closing too fast", "The closer has been adjusted too tightly and the door slams."),
        ("Signage missing from meeting room", "The room nameplate came off and has not been replaced."),
        ("Window blind mechanism broken", "The blind cannot be raised and stays fully closed all day."),
        ("Bike rack bolt sheared", "One of the stands is loose and moves when a bike is locked to it."),
    ],
}

#: Enough incidents carry these that the reporter can see a conversation, not
#: just a status change. The author role decides who posts it.
COMMENT_THREADS: list[list[tuple[str, str]]] = [
    [
        ("reporter", "This has been happening since Monday and it is making calls difficult."),
        ("engineer", "Thanks for the detail. I have logged it and will take a look this afternoon."),
        ("engineer", "I reproduced the issue and am testing a replacement unit."),
        ("reporter", "Thanks, much better today."),
    ],
    [
        ("engineer", "I have been assigned this and will be on site tomorrow morning."),
        ("reporter", "Understood, I will be at my desk from nine."),
    ],
    [
        ("reporter", "Is there any update on this? It is still happening."),
        ("engineer", "Apologies for the delay. The replacement part is on order and due Thursday."),
    ],
    [
        ("engineer", "Replacement has been requested from the supplier."),
        ("engineer", "Part arrived and has been fitted. Please confirm it is working."),
        ("reporter", "Confirmed, thank you."),
    ],
    [
        ("engineer", "Checked on site. The fault is intermittent so I am leaving a monitor on it for a few days."),
    ],
    [
        ("reporter", "Adding a note that a second person on this floor has the same problem."),
        ("engineer", "Noted, thank you. I will treat them together."),
        ("admin", "Raising the priority on this given the number of people affected."),
    ],
    [
        ("engineer", "This needs a vendor visit. I have requested a slot."),
        ("admin", "Approved. Please book the earliest available."),
        ("engineer", "Booked for Tuesday morning."),
    ],
    [
        ("reporter", "Thanks for sorting this so quickly."),
    ],
]

BLOCKED_REASONS = [
    "Replacement part awaiting delivery from the supplier.",
    "Vendor access required; waiting on a booked engineer visit.",
    "Electrical shutdown approval pending from the building manager.",
    "Waiting for a replacement monitor to arrive from stores.",
    "Building access required outside working hours.",
    "Awaiting a structural assessment before work can continue.",
]

ESCALATION_REASONS = [
    "This is stopping three people from working and has been open for over a week.",
    "Safety concern — the area is being used daily and the fault is getting worse.",
    "We have a client visit on Thursday and this is in the main meeting room.",
    "Reported twice already and it keeps recurring.",
    "The workaround we were given has stopped working.",
    "This is now affecting the whole support team's shift.",
    "Escalating as the agreed date for the repair has passed.",
    "Second week without hot water in this part of the building.",
]


# ---------------------------------------------------------------------------
# Recurring clusters
# ---------------------------------------------------------------------------
#: Deliberate recurring problems. Each entry pins the exact grouping key the
#: existing Operational Insights query uses — category plus building, floor and
#: seat ids — so these reports collapse into one underlying problem while every
#: other count in the application still sees them as separate incidents.
#:
#: ``seat`` is the index of the seat on that floor, or None for a shared space
#: with no specific desk (a corridor, a kitchen, a washroom).
RECURRING_CLUSTERS: list[dict[str, Any]] = [
    {
        "category": "TECHNOLOGY",
        "building": "ACME Headquarters",
        "floor": "Floor 3",
        "seat": 2,
        "reports": 5,
        "priorities": ["HIGH", "HIGH", "HIGH", "MEDIUM", "HIGH"],
        "statuses": [STATUS_CLOSED, STATUS_CLOSED, STATUS_RESOLVED, STATUS_IN_PROGRESS, STATUS_OPEN],
        "titles": [
            ("Monitor loses signal every few minutes", "The screen at this desk keeps dropping out and coming back."),
            ("Docking station drops the display again", "Same desk, same fault. Reconnecting the dock only helps briefly."),
            ("Workstation display failing repeatedly", "This has now happened three days running at this desk."),
            ("Screen blackouts still happening here", "Replacement cable made no difference."),
            ("Monitor at this desk still unusable", "Nobody can work at this position for more than ten minutes."),
        ],
    },
    {
        "category": "ELECTRICAL",
        "building": "Operations Center",
        "floor": "Floor 1",
        "seat": None,
        "reports": 4,
        "priorities": ["MEDIUM", "HIGH", "MEDIUM", "HIGH"],
        "statuses": [STATUS_CLOSED, STATUS_RESOLVED, STATUS_IN_PROGRESS, STATUS_BLOCKED],
        "titles": [
            ("Lights flickering across the floor", "The whole bank of lights flickers on and off."),
            ("Power tripping in this area again", "Second outage this week on the same floor."),
            ("Sockets losing power intermittently", "Equipment keeps restarting without warning."),
            ("Lighting fault has returned", "Back to flickering after the repair last week."),
        ],
    },
    {
        "category": "HVAC",
        "building": "Innovation Center",
        "floor": "Floor 2",
        "seat": None,
        "reports": 4,
        "priorities": ["MEDIUM", "MEDIUM", "MEDIUM", "LOW"],
        "statuses": [STATUS_CLOSED, STATUS_CLOSED, STATUS_RESOLVED, STATUS_OPEN],
        "titles": [
            ("This floor is far too warm again", "Uncomfortable from mid-morning onwards."),
            ("Air conditioning still not cooling", "The unit runs constantly but the air stays warm."),
            ("Temperature on this floor is unworkable", "People have started moving to other floors to work."),
            ("Cooling problem has come back", "Warm again this week despite the visit."),
        ],
    },
    {
        "category": "PLUMBING",
        "building": "Research Building",
        "floor": "Floor 1",
        "seat": None,
        "reports": 3,
        "priorities": ["MEDIUM", "HIGH", "MEDIUM"],
        "statuses": [STATUS_CLOSED, STATUS_RESOLVED, STATUS_IN_PROGRESS],
        "titles": [
            ("Washroom tap running constantly", "Water has been running all day."),
            ("Leak spreading in the washroom", "The floor is wet across most of the room now."),
            ("Water still running on this floor", "The repair last week has not held."),
        ],
    },
]

#: Status mix for the whole dataset. Most work is finished, but enough is live
#: that the current-state dashboards have something to show.
STATUS_TARGETS = {
    STATUS_OPEN: 12,
    STATUS_IN_PROGRESS: 10,
    STATUS_BLOCKED: 6,
    STATUS_RESOLVED: 22,
    STATUS_CLOSED: 50,
}

#: Category mix. Technology dominates, which is what a workplace incident desk
#: actually looks like.
CATEGORY_TARGETS = {
    "TECHNOLOGY": 34,
    "ELECTRICAL": 17,
    "HVAC": 16,
    "PLUMBING": 13,
    "FURNITURE": 12,
    "OTHER": 8,
}

PRIORITY_TARGETS = {"HIGH": 22, "MEDIUM": 52, "LOW": 26}

#: OPEN incidents left with no assignee, so the "Unassigned" bucket on the
#: admin dashboard is populated rather than empty.
UNASSIGNED_OPEN_COUNT = 8

#: How many one-off incidents may share a grouping key. Two is below
#: RECURRING_THRESHOLD, so no accidental cluster can form and the recurring
#: count on the dashboard is exactly the four defined above.
MAX_ONE_OFFS_PER_KEY = 2


# ---------------------------------------------------------------------------
# Plan structures
# ---------------------------------------------------------------------------
@dataclass
class Timeline:
    """When each lifecycle milestone happened, in seconds before seeding time.

    ``None`` means the milestone was never reached, which is exactly what the
    application stores for an incident that has not got there yet. The analytics
    average over non-NULL values only, so leaving these unset is what keeps the
    lifecycle figures honest.
    """

    created: int
    acknowledged: int | None = None
    assigned: int | None = None
    resolved: int | None = None
    closed: int | None = None
    escalated: int | None = None
    updated: int = 0


@dataclass
class CommentPlan:
    author: str  # "reporter" | "engineer" | "admin"
    body: str
    seconds_ago: int


@dataclass
class IncidentPlan:
    title: str
    description: str
    category: str
    priority: str
    status: str
    building: str
    floor: str
    seat: str | None
    reporter: int  # index into EMPLOYEE_NAMES
    engineer: int | None  # index into ENGINEER_NAMES
    timeline: Timeline
    blocked_reason: str | None = None
    escalation_reason: str | None = None
    comments: list[CommentPlan] = field(default_factory=list)
    cluster: str | None = None  # label, for the summary only


@dataclass
class DemoPlan:
    buildings: list[dict[str, Any]]
    engineers: list[dict[str, str]]
    employees: list[dict[str, str]]
    incidents: list[IncidentPlan]
    unavailable_engineers: set[int]

    @property
    def seat_count(self) -> int:
        return sum(len(floor["seats"]) for b in self.buildings for floor in b["floors"])

    @property
    def floor_count(self) -> int:
        return sum(len(b["floors"]) for b in self.buildings)

    @property
    def comment_count(self) -> int:
        return sum(len(i.comments) for i in self.incidents)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
def _email(slug: str) -> str:
    return f"{DEMO_EMAIL_PREFIX}{slug}@acme.inc"


def _build_facilities() -> list[dict[str, Any]]:
    """Expand the facility definitions into concrete floors and seat codes."""
    buildings = []
    for spec in FACILITIES:
        floors = []
        for index, floor in enumerate(spec["floors"], start=1):
            codes = [f"{spec['code']}-{index}{n:02d}" for n in range(1, floor["seats"] + 1)]
            floors.append({"name": floor["name"], "seats": codes})
        buildings.append({"name": spec["name"], "address": spec["address"], "floors": floors})
    return buildings


def _ack_delay(rng: random.Random, priority: str) -> int:
    """How long before somebody picked it up. Urgent work is looked at sooner."""
    if priority == "HIGH":
        return rng.randint(8 * 60, 75 * 60)
    if priority == "MEDIUM":
        return rng.randint(45 * 60, 7 * HOUR)
    return rng.randint(3 * HOUR, 30 * HOUR)


def _work_duration(rng: random.Random, priority: str) -> int:
    """How long the fix itself took once someone owned it.

    Deliberately wide: a few minutes for something trivial, several days for a
    part that had to be ordered. A single distribution would make every
    lifecycle average look manufactured.
    """
    roll = rng.random()
    if priority == "HIGH":
        if roll < 0.35:
            return rng.randint(20 * 60, 3 * HOUR)
        if roll < 0.8:
            return rng.randint(3 * HOUR, 12 * HOUR)
        return rng.randint(1 * DAY, 3 * DAY)
    if priority == "MEDIUM":
        if roll < 0.3:
            return rng.randint(40 * 60, 5 * HOUR)
        if roll < 0.75:
            return rng.randint(5 * HOUR, 2 * DAY)
        return rng.randint(2 * DAY, 5 * DAY)
    if roll < 0.25:
        return rng.randint(2 * HOUR, 8 * HOUR)
    if roll < 0.7:
        return rng.randint(1 * DAY, 4 * DAY)
    return rng.randint(4 * DAY, 8 * DAY)


def _timeline(rng: random.Random, status: str, priority: str, assigned: bool) -> Timeline:
    """Build a believable history for one incident.

    The milestones an incident has reached are decided by its status, which is
    what the application itself guarantees: you cannot have a ``resolved_at``
    while still OPEN. Working backwards from the status keeps the seeded rows
    indistinguishable from rows the API produced.
    """
    # Reserve room so the whole chain still fits before "now".
    created = rng.randint(_NEWEST_SECONDS_AGO, _OLDEST_SECONDS_AGO)

    timeline = Timeline(created=created, updated=created)

    if not assigned:
        # Nobody has touched it: no acknowledgement, no assignment, no more.
        return timeline

    acknowledged = max(_NEWEST_SECONDS_AGO, created - _ack_delay(rng, priority))
    # An admin triages, then assigns — usually within the same session.
    assigned_at = max(_NEWEST_SECONDS_AGO, acknowledged - rng.randint(0, 90 * 60))

    timeline.acknowledged = acknowledged
    timeline.assigned = assigned_at
    timeline.updated = assigned_at

    if status in (STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_BLOCKED):
        return timeline

    resolved = max(_NEWEST_SECONDS_AGO, assigned_at - _work_duration(rng, priority))
    timeline.resolved = resolved
    timeline.updated = resolved

    if status == STATUS_RESOLVED:
        return timeline

    # An admin reviews and accepts: anything from a couple of hours to a few days.
    closed = max(_NEWEST_SECONDS_AGO // 2, resolved - rng.randint(2 * HOUR, 3 * DAY))
    timeline.closed = closed
    timeline.updated = closed
    return timeline


def _comments_for(rng: random.Random, timeline: Timeline) -> list[CommentPlan]:
    """Pick a thread and place each message inside the incident's own lifetime.

    Comments must land after the incident was reported and before it was closed,
    because the API refuses a comment on a closed incident — seeded rows should
    not describe something the application would have rejected.
    """
    thread = rng.choice(COMMENT_THREADS)

    # The window a comment may fall in, newest bound first.
    start = timeline.created
    end = timeline.closed if timeline.closed is not None else _NEWEST_SECONDS_AGO
    if start - end < len(thread) * 600:
        return []

    step = (start - end) / (len(thread) + 1)
    comments = []
    for index, (author, body) in enumerate(thread, start=1):
        # Jitter so a thread does not look metronomic.
        offset = int(start - step * index - rng.randint(0, int(step / 3)))
        comments.append(CommentPlan(author=author, body=body, seconds_ago=max(end, offset)))
    return comments


def _location_key(building: str, floor: str, seat: str | None) -> tuple[str, str, str | None]:
    return (building, floor, seat)


def build_plan() -> DemoPlan:
    """Generate the complete demo dataset plan.

    Deterministic: the same seed produces the same plan every time.
    """
    rng = random.Random(RANDOM_SEED)
    buildings = _build_facilities()

    engineers = [{"full_name": name, "email": _email(slug)} for name, slug in ENGINEER_NAMES]
    employees = [{"full_name": name, "email": _email(slug)} for name, slug in EMPLOYEE_NAMES]

    by_name = {b["name"]: b for b in buildings}
    incidents: list[IncidentPlan] = []

    # Grouping keys already consumed, so one-off incidents cannot accidentally
    # build a fifth recurring cluster.
    key_usage: dict[tuple[str, str, str, str | None], int] = {}

    def claim(category: str, building: str, floor: str, seat: str | None, limit: int) -> bool:
        key = (category, building, floor, seat)
        if key_usage.get(key, 0) >= limit:
            return False
        key_usage[key] = key_usage.get(key, 0) + 1
        return True

    # --- The deliberate recurring clusters -------------------------------
    for cluster in RECURRING_CLUSTERS:
        building = by_name[cluster["building"]]
        floor = next(f for f in building["floors"] if f["name"] == cluster["floor"])
        seat = floor["seats"][cluster["seat"]] if cluster["seat"] is not None else None
        label = f"{cluster['category']} at {cluster['building']} > {cluster['floor']}"

        for index in range(cluster["reports"]):
            title, description = cluster["titles"][index]
            status = cluster["statuses"][index]
            priority = cluster["priorities"][index]
            assigned = status != STATUS_OPEN or index % 2 == 0
            timeline = _timeline(rng, status, priority, assigned)

            incidents.append(
                IncidentPlan(
                    title=title,
                    description=description,
                    category=cluster["category"],
                    priority=priority,
                    status=status,
                    building=building["name"],
                    floor=floor["name"],
                    seat=seat,
                    reporter=rng.randrange(len(employees)),
                    engineer=None,  # assigned in the balancing pass below
                    timeline=timeline,
                    cluster=label,
                )
            )
            # Cluster keys are consumed up to their own size so nothing else
            # lands on them.
            claim(cluster["category"], building["name"], floor["name"], seat, cluster["reports"])

    # --- One-off incidents ------------------------------------------------
    total = sum(STATUS_TARGETS.values())
    remaining_status = _remaining(STATUS_TARGETS, [i.status for i in incidents])
    remaining_category = _remaining(CATEGORY_TARGETS, [i.category for i in incidents])
    remaining_priority = _remaining(PRIORITY_TARGETS, [i.priority for i in incidents])

    status_pool = _pool(rng, remaining_status)
    category_pool = _pool(rng, remaining_category)
    priority_pool = _pool(rng, remaining_priority)
    location_pool = _location_pool(rng, buildings, len(status_pool))

    used_titles: set[str] = set()

    for index in range(len(status_pool)):
        status = status_pool[index]
        category = category_pool[index]
        priority = priority_pool[index]

        # Take the first location that does not push a grouping key to three.
        building_name, floor_name, seat = _next_free_location(
            rng, location_pool, category, claim, buildings
        )

        title, description = _pick_text(rng, category, used_titles)
        assigned = True
        timeline = _timeline(rng, status, priority, assigned)

        incidents.append(
            IncidentPlan(
                title=title,
                description=description,
                category=category,
                priority=priority,
                status=status,
                building=building_name,
                floor=floor_name,
                seat=seat,
                reporter=rng.randrange(len(employees)),
                engineer=None,
                timeline=timeline,
            )
        )

    assert len(incidents) == total, f"expected {total} incidents, planned {len(incidents)}"

    # --- Leave some OPEN incidents unassigned ----------------------------
    open_incidents = [i for i in incidents if i.status == STATUS_OPEN]
    rng.shuffle(open_incidents)
    for incident in open_incidents[:UNASSIGNED_OPEN_COUNT]:
        incident.engineer = -1  # sentinel: deliberately unassigned
        incident.timeline = Timeline(created=incident.timeline.created, updated=incident.timeline.created)

    # --- Spread the work across engineers --------------------------------
    _assign_engineers(rng, incidents)

    # --- Blocked reasons, escalations and comments ------------------------
    blocked = [i for i in incidents if i.status == STATUS_BLOCKED]
    for position, incident in enumerate(blocked):
        incident.blocked_reason = BLOCKED_REASONS[position % len(BLOCKED_REASONS)]

    _add_escalations(rng, incidents)
    _add_comments(rng, incidents)

    plan = DemoPlan(
        buildings=buildings,
        engineers=engineers,
        employees=employees,
        incidents=incidents,
        unavailable_engineers=set(UNAVAILABLE_ENGINEERS),
    )
    validate_plan(plan)
    return plan


def _remaining(targets: dict[str, int], already: list[str]) -> dict[str, int]:
    """Targets minus what the clusters already contributed."""
    counts = dict(targets)
    for value in already:
        if counts.get(value, 0) > 0:
            counts[value] -= 1
    return counts


def _pool(rng: random.Random, counts: dict[str, int]) -> list[str]:
    """A shuffled bag holding each value as many times as it is wanted."""
    pool = [value for value, n in counts.items() for _ in range(n)]
    rng.shuffle(pool)
    return pool


def _location_pool(rng: random.Random, buildings: list[dict[str, Any]], size: int) -> list[tuple]:
    """Locations drawn in proportion to each building's weight, then shuffled."""
    weighted: list[tuple[str, str, str | None]] = []
    for building in buildings:
        weight = BUILDING_WEIGHTS[building["name"]]
        for _ in range(weight * 4):
            floor = rng.choice(building["floors"])
            # Roughly two thirds of reports name a desk; the rest are shared
            # spaces, which is also what gives the seat breakdown a realistic
            # "no specific seat" bucket.
            seat = rng.choice(floor["seats"]) if rng.random() < 0.65 else None
            weighted.append((building["name"], floor["name"], seat))
    rng.shuffle(weighted)
    return weighted


def _next_free_location(rng, pool, category, claim, buildings):
    """Take a location whose grouping key still has room for another one-off."""
    while pool:
        building_name, floor_name, seat = pool.pop()
        if claim(category, building_name, floor_name, seat, MAX_ONE_OFFS_PER_KEY):
            return building_name, floor_name, seat

    # Exhausted the weighted pool — fall back to any key with room. Reached only
    # if the weights are retuned badly, and loud rather than silent.
    for building in buildings:
        for floor in building["floors"]:
            for seat in [None, *floor["seats"]]:
                if claim(category, building["name"], floor["name"], seat, MAX_ONE_OFFS_PER_KEY):
                    return building["name"], floor["name"], seat
    raise RuntimeError("No location left that keeps one-off incidents below the recurring threshold")


def _pick_text(rng: random.Random, category: str, used: set[str]) -> tuple[str, str]:
    """A title and description for this category, avoiding repeats where possible."""
    options = INCIDENT_TEMPLATES[category]
    for _ in range(len(options) * 2):
        title, description = rng.choice(options)
        if title not in used:
            used.add(title)
            return title, description
    # More incidents than distinct wordings: qualify the repeat rather than
    # filing two identical-looking reports.
    title, description = rng.choice(options)
    return f"{title} (reported again)", description


def _assign_engineers(rng: random.Random, incidents: list[IncidentPlan]) -> None:
    """Give each engineer the active workload the targets ask for.

    Active means anything not CLOSED, which is the same definition the workload
    panel uses — so the numbers here are the numbers the dashboard will show.
    """
    active = [i for i in incidents if i.status != STATUS_CLOSED and i.engineer != -1]
    rng.shuffle(active)

    queue: list[int] = []
    for engineer_index, target in enumerate(ENGINEER_ACTIVE_TARGETS):
        queue.extend([engineer_index] * target)

    for incident, engineer_index in zip(active, queue):
        incident.engineer = engineer_index

    # Any active incident left over (targets sum lower than the count) goes to
    # the least loaded engineer, so nothing is silently left unassigned.
    load = {index: 0 for index in range(len(ENGINEER_ACTIVE_TARGETS))}
    for incident in active:
        if incident.engineer is not None and incident.engineer >= 0:
            load[incident.engineer] += 1
    for incident in active:
        if incident.engineer is None:
            least = min(load, key=lambda key: load[key])
            incident.engineer = least
            load[least] += 1

    # Closed work is spread evenly — it is history, not current load.
    closed = [i for i in incidents if i.status == STATUS_CLOSED]
    rng.shuffle(closed)
    for position, incident in enumerate(closed):
        incident.engineer = position % len(ENGINEER_ACTIVE_TARGETS)


def _add_escalations(rng: random.Random, incidents: list[IncidentPlan]) -> None:
    """Flag a handful of live incidents as escalated by their reporter.

    Only incidents in a status the API would accept an escalation for, so the
    seeded rows match what the endpoint itself permits.
    """
    candidates = [
        i for i in incidents
        if i.status in (STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_BLOCKED)
    ]
    rng.shuffle(candidates)

    for position, incident in enumerate(candidates[: len(ESCALATION_REASONS)]):
        incident.escalation_reason = ESCALATION_REASONS[position]
        # Escalated some time after it was reported, never before.
        incident.timeline.escalated = max(
            _NEWEST_SECONDS_AGO,
            incident.timeline.created - rng.randint(6 * HOUR, 4 * DAY),
        )


def _add_comments(rng: random.Random, incidents: list[IncidentPlan]) -> None:
    """Put conversations on a subset of incidents, weighted towards the ones a
    reporter would actually have chased."""
    for incident in incidents:
        # Escalated and blocked work almost always has a conversation attached;
        # routine tickets often have none at all.
        if incident.escalation_reason or incident.status == STATUS_BLOCKED:
            chance = 0.95
        elif incident.status in (STATUS_CLOSED, STATUS_RESOLVED):
            chance = 0.3
        else:
            chance = 0.5

        if rng.random() > chance:
            continue
        if incident.engineer is None or incident.engineer < 0:
            # Nobody is on it yet, so there is no engineer to reply.
            continue
        incident.comments = _comments_for(rng, incident.timeline)


def validate_plan(plan: DemoPlan) -> None:
    """Fail loudly if the plan would not demo the way it is supposed to.

    These are the guarantees the seeder advertises, checked before a single row
    is written rather than discovered on the dashboard during a presentation.
    """
    window = OPERATIONAL_WINDOW_DAYS * DAY
    for incident in plan.incidents:
        assert incident.timeline.created < window, "an incident falls outside the analytics window"
        assert incident.timeline.created > 0, "an incident is stamped in the future"

        chain = [
            incident.timeline.created,
            incident.timeline.acknowledged,
            incident.timeline.assigned,
            incident.timeline.resolved,
            incident.timeline.closed,
        ]
        reached = [value for value in chain if value is not None]
        assert reached == sorted(reached, reverse=True), (
            f"lifecycle timestamps out of order on {incident.title!r}"
        )

        if incident.status in (STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_BLOCKED):
            assert incident.timeline.resolved is None and incident.timeline.closed is None, (
                "a live incident carries a completion timestamp"
            )
        if incident.status == STATUS_RESOLVED:
            assert incident.timeline.resolved is not None, "RESOLVED without resolved_at"
            assert incident.timeline.closed is None, "RESOLVED carries closed_at"
        if incident.status == STATUS_CLOSED:
            assert incident.timeline.closed is not None, "CLOSED without closed_at"
        if incident.status == STATUS_BLOCKED:
            assert incident.blocked_reason, "BLOCKED without a reason"

    # The grouping rule the dashboard uses, reproduced here so the promised
    # number of clusters is verified before anything is written.
    groups: dict[tuple, int] = {}
    for incident in plan.incidents:
        key = (incident.category, incident.building, incident.floor, incident.seat)
        groups[key] = groups.get(key, 0) + 1

    clusters = [key for key, count in groups.items() if count >= RECURRING_THRESHOLD]
    assert len(clusters) == len(RECURRING_CLUSTERS), (
        f"expected {len(RECURRING_CLUSTERS)} recurring clusters, plan produces {len(clusters)}"
    )


def recurring_cluster_count() -> int:
    return len(RECURRING_CLUSTERS)
