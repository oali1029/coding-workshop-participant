"""Deciding which function handles an incoming URL, and who is allowed to.

=============================================================================
WHAT THIS FILE IS RESPONSIBLE FOR
=============================================================================
Two jobs, both applied to every request:

    ROUTING        "GET /incidents/42" means "run the fetch-one-incident
                   function, and tell it the id is 42".

    AUTHORIZATION  before that function runs, confirm the caller is signed in
                   and holds a role the route permits.

Larger projects use a framework such as Flask or FastAPI for routing. We write
it by hand, in about two hundred lines, for two reasons: every extra library
has to be packaged into the Lambda upload and slows cold starts, and a
hand-written router makes the request flow completely visible rather than
hidden inside someone else's abstraction.

=============================================================================
WHY PERMISSIONS ARE DECLARED HERE AND NOT INSIDE EACH HANDLER
=============================================================================
Each route states who may call it, right next to the URL:

    Route("GET", "/auth/me", auth.me, roles=security.ANY_AUTHENTICATED)

`dispatch` enforces that centrally, before the handler is called. The handler
itself contains no permission logic at all.

This matters because the most common way an application leaks data is not a
broken check — it is a MISSING one. If each handler did its own checking, a new
endpoint added in a hurry would default to "wide open", and nothing would look
wrong in review. Here, a route cannot be added without writing down its access
rule, and the whole permission model can be audited by reading one list.

=============================================================================
THE MOST IMPORTANT THING IN THIS FILE: THE URL PREFIX PROBLEM
=============================================================================
Read this section carefully — it is the single most likely cause of a bug that
looks like "it works on my laptop but returns 404 on AWS".

Our API lives under "/api/v1". That prefix is not decoration: it is how the
infrastructure tells API calls apart from requests for the React app itself.
But the two environments handle it DIFFERENTLY.

  ON AWS, via CloudFront
      CloudFront matches the rule "/api/v1*" and forwards the request to the
      Lambda WITHOUT changing the URL. Our handler receives the full path:

          /api/v1/auth/login

  ON A LAPTOP, via the development proxy (bin/proxy-server.js)
      That proxy is a small helper script the workshop provides. It splits the
      URL into "/api/{service}" plus the rest, looks up the service's address,
      and forwards ONLY THE REST. Our handler receives:

          /auth/login

Same browser request, two different paths arriving at our code. If we wrote
our routes as "/api/v1/auth/login" they would only work on AWS; if we wrote
them as "/auth/login" they would only work locally.

The fix is `strip_service_prefix` below. We remove the prefix if it is there,
leaving a consistent path in both environments, and then define every route
WITHOUT the prefix. One set of routes, correct everywhere.

=============================================================================
HOW A ROUTE PATTERN IS MATCHED
=============================================================================
Routes are written like "/incidents/{id}". Matching works by splitting both
the pattern and the real path on "/" and comparing piece by piece:

    pattern:  ["incidents", "{id}"]
    actual:   ["incidents", "42"]

A piece wrapped in braces matches anything and captures it; any other piece
must match exactly. So "/incidents/{id}" matches "/incidents/42" and records
{"id": "42"}, but does not match "/incidents/42/notes", which has more pieces.

Captured values are always STRINGS, because a URL is text. Handlers that need
a number must convert and validate it themselves.
"""

import logging
from dataclasses import dataclass
from typing import Any, Callable

from . import security
from .domains import auth, health
from .errors import AppError, NotFoundError
from .http import Request

logger = logging.getLogger(__name__)

# The URL prefix this service answers on.
#
# "v1" is also the name of this service's folder (backend/v1), which is not a
# coincidence: the infrastructure derives the public route from the folder
# name. Renaming the folder would silently change the API's address, so these
# two things must be kept in step.
SERVICE_PREFIX = "/api/v1"

# A handler takes our Request and returns the response dictionary AWS expects.
Handler = Callable[[Request], dict[str, Any]]


@dataclass(frozen=True)
class Route:
    """One endpoint: a URL, the function behind it, and who may call it.

    Attributes:
        method: HTTP verb this route answers.
        pattern: Path pattern without the service prefix, e.g. "/auth/login".
        handler: Function to run.
        roles: Which roles may call it. `None` means the endpoint is PUBLIC —
            written explicitly so that "anyone may call this" is a visible
            decision in the route table rather than an omission.
    """

    method: str
    pattern: str
    handler: Handler
    roles: frozenset[str] | None = None


# =============================================================================
# THE ROUTE TABLE — the complete, auditable surface of this API
# =============================================================================
# Read the `roles` column to understand the security model at a glance:
#
#   None                       public, no token needed
#   security.ANY_AUTHENTICATED any signed-in user, whatever their role
#   frozenset({...})           only the listed roles
#
# Later slices add incident, facility and reporting routes here.
ROUTES: list[Route] = [
    # Public: the system status check. No token, because monitoring needs to
    # reach it and it exposes nothing sensitive.
    Route("GET", "/health", health.get_health, roles=None),

    # Public by necessity: a person cannot hold a token before they have an
    # account or have signed in.
    Route("POST", "/auth/register", auth.register, roles=None),
    Route("POST", "/auth/login", auth.login, roles=None),

    # Protected: requires a valid token, but any role will do. Used by the
    # React app on startup to turn a stored token back into a name and role.
    Route("GET", "/auth/me", auth.me, roles=security.ANY_AUTHENTICATED),
]


def strip_service_prefix(path: str) -> str:
    """Remove the "/api/v1" prefix if present, so routes match in both environments.

    See the module docstring for why the prefix is sometimes there and
    sometimes not. This function is what makes that difference invisible to
    the rest of the application.

    Args:
        path: The raw path as it arrived, with or without the prefix.

    Returns:
        The path with the prefix removed, always beginning with "/".

    Examples:
        "/api/v1/auth/login" -> "/auth/login"   (arrived via CloudFront)
        "/auth/login"        -> "/auth/login"   (arrived via the local proxy)
        "/api/v1"            -> "/"             (the bare prefix, no sub-path)
        "/api/v1/"           -> "/"
    """
    if path.startswith(SERVICE_PREFIX):
        path = path[len(SERVICE_PREFIX):]

    # Removing the prefix can leave an empty string, or a path with no leading
    # slash. Normalising here means matching logic below never has to special-
    # case those.
    if not path.startswith("/"):
        path = "/" + path

    # Treat "/health/" and "/health" as the same route. Browsers, proxies and
    # people are all inconsistent about trailing slashes, and a 404 caused by
    # one is a frustrating and entirely avoidable bug. The `len(path) > 1`
    # guard stops us turning the root path "/" into an empty string.
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    return path


def _match(pattern: str, path: str) -> dict[str, str] | None:
    """Test one route pattern against a real path.

    Args:
        pattern: A route pattern, e.g. "/incidents/{id}".
        path: The requested path, already stripped of the service prefix.

    Returns:
        A dictionary of captured values when the pattern matches — empty if the
        pattern contains no braces — or None when it does not match.

        Returning an empty dict for a match and None for a miss is deliberate:
        an empty dict is "falsy" in Python, so callers must compare against
        None explicitly rather than writing `if _match(...)`, which would
        wrongly treat a successful match with no parameters as a failure.
    """
    # `strip("/")` removes the leading slash so splitting does not produce a
    # leading empty piece. "/incidents/42" becomes ["incidents", "42"].
    pattern_parts = pattern.strip("/").split("/")
    path_parts = path.strip("/").split("/")

    # Different number of segments can never match. Checking first avoids
    # comparing pieces that do not line up.
    if len(pattern_parts) != len(path_parts):
        return None

    params: dict[str, str] = {}

    for pattern_part, path_part in zip(pattern_parts, path_parts):
        if pattern_part.startswith("{") and pattern_part.endswith("}"):
            # A placeholder: capture whatever is here under the name inside the
            # braces. "{id}" becomes the key "id".
            params[pattern_part[1:-1]] = path_part
        elif pattern_part != path_part:
            # A literal segment that does not match; this route is not it.
            return None

    return params


def dispatch(request: Request) -> dict[str, Any]:
    """Find the handler for this request, check permissions, and run it.

    This is step 5 of the request journey described in app/__init__.py, and the
    single point at which every authorization decision is made.

    Args:
        request: The parsed request. Its `path` is normalised here, and
            `path_params` and `user` are filled in before the handler runs.

    Returns:
        Whatever the matched handler returned.

    Raises:
        NotFoundError: No route pattern matched the path at all.
        AppError: A route matched the path but not the HTTP method (405).
        UnauthorizedError: The route needs a token and none was valid (401).
        ForbiddenError: The caller is known but lacks the required role (403).
    """
    request.path = strip_service_prefix(request.path)

    # Tracks whether some route matched the path but with a different method.
    # This lets us tell "/incidents does not exist" apart from "/incidents
    # exists but you cannot DELETE it" — a far more useful message when
    # debugging, and the distinction HTTP intends between 404 and 405.
    path_matched = False

    for route in ROUTES:
        params = _match(route.pattern, request.path)
        if params is None:
            continue

        path_matched = True

        if route.method != request.method:
            continue

        # ---------------------------------------------------------------
        # THE SECURITY GATE. Everything past this point is a permitted call.
        # ---------------------------------------------------------------
        # Order matters and mirrors the two HTTP status codes:
        #   authenticate first  -> "who are you?"      -> 401 if unanswerable
        #   then authorize      -> "may you do this?"  -> 403 if not
        #
        # `roles is None` means the route is public, so both steps are skipped
        # and `request.user` stays None.
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
        raise AppError(
            f"The {request.method} method is not supported for this endpoint.",
            status=405,
            code="method_not_allowed",
        )

    raise NotFoundError(f"No endpoint matches {request.method} {request.path}.")
