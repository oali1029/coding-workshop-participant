"""URL matching and the route table, including the central permission gate.

Routing is hand-written rather than taken from a framework: every dependency
has to be packaged into the Lambda zip and paid for at cold start, and the
whole request path stays visible.

Permissions are declared per route and enforced here, not inside handlers. The
common way applications leak data is not a broken check but a missing one — a
new endpoint added in a hurry that nobody notices is unprotected. Declaring the
rule alongside the URL makes the entire access model readable in one list.

THE URL PREFIX DIFFERENCE, which is the most likely cause of "works locally,
404s on AWS": CloudFront matches ``/api/v1*`` and forwards the request with the
path intact, so the Lambda sees ``/api/v1/auth/login``. The local dev proxy
(bin/proxy-server.js) instead strips ``/api/{service}`` and forwards only the
remainder, so the Lambda sees ``/auth/login``. :func:`strip_service_prefix`
normalises both, and routes are declared without the prefix.
"""

import logging
from dataclasses import dataclass
from typing import Any, Callable

from . import security
from .domains import auth, health, incidents, users
from .errors import MethodNotAllowedError, NotFoundError
from .http import Request

logger = logging.getLogger(__name__)

# Must match this service's folder name (backend/v1): the infrastructure
# derives the public route from it, so renaming the folder changes the API's
# address.
SERVICE_PREFIX = "/api/v1"

Handler = Callable[[Request], dict[str, Any]]


@dataclass(frozen=True)
class Route:
    """One endpoint and who may call it.

    Attributes:
        pattern: Path without the service prefix. ``{name}`` segments match
            anything and are captured into ``request.path_params``.
        roles: ``None`` means public — written explicitly so that "anyone may
            call this" is a visible decision rather than an omission.
    """

    method: str
    pattern: str
    handler: Handler
    roles: frozenset[str] | None = None


# The complete API surface. Read the roles column to see the security model.
ROUTES: list[Route] = [
    Route("GET", "/health", health.get_health, roles=None),
    # Public by necessity: a caller cannot hold a token before signing in.
    Route("POST", "/auth/register", auth.register, roles=None),
    Route("POST", "/auth/login", auth.login, roles=None),
    Route("GET", "/auth/me", auth.me, roles=security.ANY_AUTHENTICATED),
    # Any signed-in user may report and track their own incidents — engineers
    # and admins are staff who also hit broken taps. Which incidents they can
    # actually see is decided per row inside the handlers, not here.
    Route("POST", "/incidents", incidents.create, roles=security.ANY_AUTHENTICATED),
    Route("GET", "/incidents", incidents.list_mine, roles=security.ANY_AUTHENTICATED),
    Route("GET", "/incidents/{id}", incidents.get_one, roles=security.ANY_AUTHENTICATED),
    # Facility Admin oversight and team management. Separate paths rather than
    # role-aware versions of the routes above, so the access rule is visible
    # here instead of buried in a handler.
    Route("GET", "/admin/incidents", incidents.list_all, roles=security.FACILITY_ADMIN_ONLY),
    Route("GET", "/users", users.list_all, roles=security.FACILITY_ADMIN_ONLY),
    Route("PATCH", "/users/{id}/role", users.set_role, roles=security.FACILITY_ADMIN_ONLY),
]


def strip_service_prefix(path: str) -> str:
    """Remove the ``/api/v1`` prefix if present, so routes match in both environments.

    Examples:
        "/api/v1/auth/login" -> "/auth/login"   (CloudFront)
        "/auth/login"        -> "/auth/login"   (local proxy)
        "/api/v1"            -> "/"
    """
    if path.startswith(SERVICE_PREFIX):
        path = path[len(SERVICE_PREFIX):]

    if not path.startswith("/"):
        path = "/" + path

    # Treat "/health/" and "/health" alike; clients are inconsistent about
    # trailing slashes and a 404 from one is an avoidable bug.
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    return path


def _match(pattern: str, path: str) -> tuple[bool, dict[str, str]]:
    """Check a route pattern against a request path.

    Compares the two a segment at a time. A ``{name}`` segment matches anything
    and is captured; every other segment must match exactly.

        "/incidents/{id}" vs "/incidents/42"  ->  (True, {"id": "42"})

    Returns (matched, params). The separate boolean matters: a route with no
    ``{name}`` segments matches with an empty params dict, and an empty dict is
    falsy in Python, so testing the dict alone would treat a successful match as
    a failure.
    """
    pattern_parts = pattern.strip("/").split("/")
    path_parts = path.strip("/").split("/")

    if len(pattern_parts) != len(path_parts):
        return False, {}

    params: dict[str, str] = {}

    for pattern_part, path_part in zip(pattern_parts, path_parts):
        if pattern_part.startswith("{") and pattern_part.endswith("}"):
            params[pattern_part[1:-1]] = path_part
        elif pattern_part != path_part:
            return False, {}

    return True, params


def dispatch(request: Request) -> dict[str, Any]:
    """Match the request to a route, enforce its access rule, and run it.

    Raises:
        NotFoundError: nothing matched the path (404).
        AppError: the path matched but not the method (405).
        UnauthorizedError / ForbiddenError: raised by the security gate.
    """
    request.path = strip_service_prefix(request.path)

    # Distinguishes "/incidents does not exist" from "you cannot DELETE
    # /incidents", which is the difference HTTP intends between 404 and 405.
    path_matched = False

    for route in ROUTES:
        matched, params = _match(route.pattern, request.path)
        if not matched:
            continue

        path_matched = True

        if route.method != request.method:
            continue

        # Authenticate before authorizing: "who are you" (401) must be answered
        # before "may you do this" (403).
        if route.roles is not None:
            request.user = security.authenticate_request(request)
            security.require_roles(request.user, route.roles)

        request.path_params = params

        logger.info(
            "Routing %s %s to %s (user=%s)",
            request.method,
            request.path,
            route.handler.__name__,
            request.user["id"] if request.user else "anonymous",
        )

        return route.handler(request)

    if path_matched:
        raise MethodNotAllowedError(
            f"The {request.method} method is not supported for this endpoint."
        )

    raise NotFoundError(f"No endpoint matches {request.method} {request.path}.")
