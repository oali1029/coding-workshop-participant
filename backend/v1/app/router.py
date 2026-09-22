"""Deciding which function handles an incoming URL.

=============================================================================
WHAT THIS FILE IS RESPONSIBLE FOR
=============================================================================
A request arrives saying "GET /incidents/42". Something has to decide that
this means "run the function that fetches one incident, and tell it the id is
42". That decision is called routing, and this file does it.

Larger projects use a framework such as Flask or FastAPI for this. We write it
by hand, in about a hundred lines, for two reasons: every extra library has to
be packaged into the Lambda upload and slows cold starts, and a hand-written
router makes the request flow completely visible rather than hidden inside
someone else's abstraction.

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

          /api/v1/incidents/42

  ON A LAPTOP, via the development proxy (bin/proxy-server.js)
      That proxy is a small helper script the workshop provides. It splits the
      URL into "/api/{service}" plus the rest, looks up the service's address,
      and forwards ONLY THE REST. Our handler receives:

          /incidents/42

Same browser request, two different paths arriving at our code. If we wrote
our routes as "/api/v1/incidents" they would only work on AWS; if we wrote
them as "/incidents" they would only work locally.

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
from typing import Any, Callable

from .domains import health
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

# The routing table: (HTTP method, URL pattern, function to run).
#
# Keeping every route in one visible list means you can read the API's entire
# surface at a glance. Later slices append their routes here.
ROUTES: list[tuple[str, str, Handler]] = [
    ("GET", "/health", health.get_health),
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
        "/api/v1/incidents" -> "/incidents"    (arrived via CloudFront)
        "/incidents"        -> "/incidents"    (arrived via the local proxy)
        "/api/v1"           -> "/"             (the bare prefix, no sub-path)
        "/api/v1/"          -> "/"
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
    """Find the handler for this request, run it, and return its response.

    This is step 5 of the request journey described in app/__init__.py.

    Args:
        request: The parsed request. Its `path` is normalised here before
            matching, and `path_params` is filled in before the handler runs.

    Returns:
        Whatever the matched handler returned.

    Raises:
        NotFoundError: No route pattern matched the path at all.
        AppError: A route matched the path but not the HTTP method, returned
            as 405 Method Not Allowed.
    """
    request.path = strip_service_prefix(request.path)

    # Tracks whether some route matched the path but with a different method.
    # This lets us tell "/incidents does not exist" apart from "/incidents
    # exists but you cannot DELETE it" — a far more useful message when
    # debugging, and the distinction HTTP intends between 404 and 405.
    path_matched = False

    for method, pattern, handler in ROUTES:
        params = _match(pattern, request.path)
        if params is None:
            continue

        path_matched = True

        if method != request.method:
            continue

        # Hand the captured URL values to the handler via the request object,
        # so handlers never have to parse URLs themselves.
        request.path_params = params
        logger.info("Routing %s %s to %s", request.method, request.path, handler.__name__)
        return handler(request)

    if path_matched:
        raise AppError(
            f"The {request.method} method is not supported for this endpoint.",
            status=405,
            code="method_not_allowed",
        )

    raise NotFoundError(f"No endpoint matches {request.method} {request.path}.")
