"""Translating AWS Lambda events into requests, and results back into responses.

=============================================================================
WHAT THIS FILE IS RESPONSIBLE FOR
=============================================================================
This is the border crossing between "how AWS talks" and "how our application
talks". It does two jobs:

  IN:  take the large, awkwardly-shaped dictionary AWS hands us and produce a
       small, predictable Request object.
  OUT: take a plain Python value and wrap it in the exact dictionary shape AWS
       requires for an HTTP response.

Because this translation lives here, no other file in the project needs to
know anything about AWS. If the platform changed tomorrow, only this file and
../function.py would need rewriting.

=============================================================================
BACKGROUND: WHAT A LAMBDA ACTUALLY RECEIVES
=============================================================================
Normal web frameworks hand you a request object. Lambda does not. It calls our
function with a plain dictionary, and the exact keys depend on which AWS
service triggered it.

We are triggered by a "Lambda Function URL", which delivers what AWS calls
payload format 2.0. The parts we care about look roughly like this:

    {
      "requestContext": {"http": {"method": "POST", "path": "/api/v1/incidents"}},
      "headers":        {"content-type": "application/json", ...},
      "queryStringParameters": {"status": "OPEN"},
      "body":           "{\\"title\\": \\"Broken AC\\"}",   <- a STRING, not a dict
      "isBase64Encoded": false
    }

Two details catch people out, and both are handled below:

  * "body" is a STRING containing JSON, not a parsed object. It must be
    decoded manually.
  * AWS sometimes base64-encodes the body. When it does, it sets
    "isBase64Encoded" to true and we must decode twice: base64 first, then
    JSON.
"""

import base64
import json
from dataclasses import dataclass, field
from typing import Any

from .errors import ValidationError

# Headers attached to every response we send.
#
# "no-store" is deliberate. CloudFront is a caching network sitting in front of
# this API, and caching an API response would be actively harmful: one user
# could be served another user's incident list. The infrastructure also sets a
# no-caching policy on the /api/v1 route, so this is a second layer of defence.
DEFAULT_HEADERS: dict[str, str] = {
    "Content-Type": "application/json",
    "Cache-Control": "no-store",
}


@dataclass
class Request:
    """One incoming HTTP request, in a shape our own code finds convenient.

    A dataclass is simply a class whose job is to hold named values; Python
    writes the boilerplate constructor for us.

    Attributes:
        method: The HTTP verb, upper-cased — "GET", "POST", "PATCH", "DELETE".
        path: The part of the URL after the domain, with the "/api/v1" prefix
            already removed by the router. Handlers therefore see "/incidents"
            regardless of how the request reached us.
        headers: Header names lower-cased, because HTTP header names are
            case-insensitive and different clients capitalise differently.
            Lower-casing once here means lookups elsewhere are reliable.
        query: Values after the "?" in the URL, used for filtering and paging.
        body: The request body already decoded from JSON, or None.
        raw_body: The original undecoded text, kept only for debugging.
        path_params: Values pulled out of the URL pattern by the router. For
            the route "/incidents/{id}" matching "/incidents/42", this holds
            {"id": "42"}.
        user: The signed-in user's database row, filled in by the router for
            routes that require authentication. It stays None on public routes,
            so a handler reading `request.user` without its route declaring an
            access rule will fail loudly rather than silently treating the
            caller as anonymous.
    """

    method: str
    path: str
    # `field(default_factory=dict)` creates a NEW empty dictionary for each
    # Request. Writing `= {}` would share one dictionary between every request
    # ever created — a classic Python bug that would leak one user's data into
    # another user's request.
    headers: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)
    body: Any = None
    raw_body: str = ""
    path_params: dict[str, str] = field(default_factory=dict)
    user: dict[str, Any] | None = None

    def json_body(self) -> dict[str, Any]:
        """Return the body as a JSON object, refusing anything else.

        Handlers that create or update records call this instead of reading
        `.body` directly, so that a missing or malformed body produces a clean
        400 error rather than an AttributeError crash deeper in the code.

        Returns:
            The decoded body dictionary.

        Raises:
            ValidationError: If the body was absent, was not valid JSON, or
                was valid JSON but not an object (for example a bare list or
                a number).
        """
        if not isinstance(self.body, dict):
            raise ValidationError("Request body must be a JSON object.")
        return self.body

    def header(self, name: str, default: str | None = None) -> str | None:
        """Look up a header without worrying about capitalisation.

        Callers can ask for "Authorization" even though we stored
        "authorization", because this lower-cases the name before looking.
        """
        return self.headers.get(name.lower(), default)


def _decode_body(event: dict[str, Any]) -> tuple[Any, str]:
    """Turn the event's body string into a Python value.

    Handles the two-layer encoding described in the module docstring: base64
    on the outside (sometimes), JSON on the inside.

    Args:
        event: The raw Lambda event.

    Returns:
        A pair of (parsed value, original text). The parsed value is None when
        the body is empty or is not valid JSON. We return None rather than
        raising here because a missing body is perfectly legal for GET and
        DELETE requests — only handlers that require a body should complain,
        which they do via `Request.json_body()`.
    """
    raw = event.get("body") or ""

    # AWS base64-encodes bodies it considers binary. We must undo that before
    # attempting to read JSON, or json.loads would see meaningless characters.
    if event.get("isBase64Encoded") and raw:
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            # Genuinely binary content (an uploaded image, say) cannot become
            # text. We are a JSON-only API, so we treat it as "no body" and
            # let the handler decide whether that is acceptable.
            return None, ""

    if not raw.strip():
        return None, raw

    try:
        return json.loads(raw), raw
    except json.JSONDecodeError:
        # Malformed JSON. Again we do not raise here — we hand back None and
        # keep the original text so it can be logged while debugging.
        return None, raw


def parse_request(event: dict[str, Any]) -> Request:
    """Convert a raw Lambda event into our Request object.

    This is step 4 of the request journey described in app/__init__.py.

    Args:
        event: The dictionary AWS passes to the Lambda handler.

    Returns:
        A populated Request. Note that `path` still includes the "/api/v1"
        prefix at this stage; the router strips it immediately afterwards.
    """
    # Payload format 2.0 nests the method and path inside requestContext.http.
    # The `or {}` guards are important: if a key is missing we want an empty
    # dictionary to keep chaining from, not a TypeError on None.
    http_ctx = (event.get("requestContext") or {}).get("http") or {}

    # We read the modern location first, then fall back to the older payload
    # format 1.0 field names ("httpMethod", "path"). This is not paranoia:
    # LocalStack, the tool we use to emulate AWS on a laptop, is not always
    # consistent with real AWS here. Supporting both means the same code runs
    # locally and in the cloud without a special case.
    method = (http_ctx.get("method") or event.get("httpMethod") or "GET").upper()
    path = http_ctx.get("path") or event.get("rawPath") or event.get("path") or "/"

    raw_headers = event.get("headers") or {}
    headers = {str(k).lower(): str(v) for k, v in raw_headers.items()}

    # Query parameters can legitimately be absent, in which case AWS sends
    # None rather than an empty dictionary. We also drop any individual value
    # that is None so handlers never have to check for it.
    query = {
        str(k): str(v)
        for k, v in (event.get("queryStringParameters") or {}).items()
        if v is not None
    }

    body, raw_body = _decode_body(event)

    return Request(
        method=method,
        path=path,
        headers=headers,
        query=query,
        body=body,
        raw_body=raw_body,
    )


def response(
    status: int,
    body: Any = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the response dictionary that AWS turns into a real HTTP reply.

    AWS requires exactly these three keys. Returning anything else — including
    returning our data directly — produces a 502 error, because AWS cannot
    work out what HTTP response we meant.

    Args:
        status: HTTP status code, e.g. 200 or 404.
        body: Any value that can be represented as JSON. Passing None produces
            an empty body, which is what a 204 "No Content" reply requires.
        headers: Extra headers merged on top of DEFAULT_HEADERS.

    Returns:
        The dictionary AWS expects.
    """
    merged = {**DEFAULT_HEADERS, **(headers or {})}

    # `default=str` tells json.dumps what to do when it meets a value it does
    # not natively understand. Our database returns datetime objects for
    # columns like created_at, and without this the call would crash. Turning
    # them into strings yields ISO-8601 timestamps, which JavaScript's
    # `new Date(...)` reads directly.
    payload = "" if body is None else json.dumps(body, default=str)

    return {"statusCode": status, "headers": merged, "body": payload}


def ok(body: Any) -> dict[str, Any]:
    """200 OK — the request succeeded and here is the data."""
    return response(200, body)


def created(body: Any) -> dict[str, Any]:
    """201 Created — a new record was stored. Used by POST handlers."""
    return response(201, body)


def no_content() -> dict[str, Any]:
    """204 No Content — it worked and there is deliberately nothing to send.

    Used after a successful DELETE, where returning the thing we just deleted
    would be odd.
    """
    return response(204, None)
