"""Translating Lambda Function URL events into requests, and results into responses.

Lambda hands us a dictionary rather than a request object, and its exact shape
depends on the trigger. Confining that translation here means no other module
needs to know anything about AWS.

Two details of the payload catch people out, and both are handled below: the
body arrives as a JSON *string* rather than a parsed object, and AWS sometimes
base64-encodes it on top of that.
"""

import base64
import json
from dataclasses import dataclass, field
from typing import Any

from .errors import ValidationError

# `no-store` is deliberate: CloudFront sits in front of this API, and a cached
# API response could serve one user's data to another. The infrastructure also
# applies a no-caching policy to /api/v1, so this is a second layer.
DEFAULT_HEADERS: dict[str, str] = {
    "Content-Type": "application/json",
    "Cache-Control": "no-store",
}


@dataclass
class Request:
    """A normalised inbound request.

    Attributes:
        path: Service prefix already removed by the router, so handlers always
            see ``/auth/login`` regardless of how the request arrived.
        headers: Names lower-cased, since HTTP headers are case-insensitive and
            clients capitalise them differently.
        path_params: Values captured from the route pattern, e.g. ``{"id": "42"}``.
        user: Populated by the router for authenticated routes, left None on
            public ones so a handler reading it without an access rule fails
            loudly rather than treating the caller as anonymous.
    """

    method: str
    path: str
    headers: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)
    body: Any = None
    raw_body: str = ""
    path_params: dict[str, str] = field(default_factory=dict)
    user: dict[str, Any] | None = None

    def json_body(self) -> dict[str, Any]:
        """Return the body as a JSON object, or raise ValidationError.

        Handlers that write data use this rather than reading ``.body``
        directly, so a missing or malformed body becomes a clean 400 instead of
        an AttributeError deeper in the call stack.
        """
        if not isinstance(self.body, dict):
            raise ValidationError("Request body must be a JSON object.")
        return self.body

    def header(self, name: str, default: str | None = None) -> str | None:
        """Look up a header case-insensitively."""
        return self.headers.get(name.lower(), default)


def _decode_body(event: dict[str, Any]) -> tuple[Any, str]:
    """Decode the event body, undoing base64 first when AWS applied it.

    Returns ``(parsed, raw)``, with ``parsed`` None when the body is absent or
    not valid JSON. Absence is not an error here — GET and DELETE legitimately
    have no body, and only handlers that require one should complain.
    """
    raw = event.get("body") or ""

    if event.get("isBase64Encoded") and raw:
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            # Genuinely binary content cannot become text. This is a JSON-only
            # API, so treat it as no body.
            return None, ""

    if not raw.strip():
        return None, raw

    try:
        return json.loads(raw), raw
    except json.JSONDecodeError:
        return None, raw


def parse_request(event: dict[str, Any]) -> Request:
    """Build a Request from a raw Lambda event.

    Reads payload format 2.0 first and falls back to the 1.0 field names,
    because LocalStack is not always consistent with AWS here. Supporting both
    keeps one code path for local and deployed environments.

    The returned path still carries the ``/api/v1`` prefix; the router strips it.
    """
    http_ctx = (event.get("requestContext") or {}).get("http") or {}
    method = (http_ctx.get("method") or event.get("httpMethod") or "GET").upper()
    path = http_ctx.get("path") or event.get("rawPath") or event.get("path") or "/"

    headers = {str(k).lower(): str(v) for k, v in (event.get("headers") or {}).items()}

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
    """Build the three-key dictionary AWS turns into an HTTP response.

    Returning any other shape produces a 502, because AWS cannot interpret it.
    A body of None yields an empty string, which is what 204 requires.
    """
    merged = {**DEFAULT_HEADERS, **(headers or {})}

    # `default=str` handles the datetime objects the database returns, which
    # json.dumps cannot serialise natively. The result is ISO-8601 text that
    # JavaScript's `new Date(...)` parses directly.
    payload = "" if body is None else json.dumps(body, default=str)

    return {"statusCode": status, "headers": merged, "body": payload}


def ok(body: Any) -> dict[str, Any]:
    """200 OK."""
    return response(200, body)


def created(body: Any) -> dict[str, Any]:
    """201 Created."""
    return response(201, body)


def no_content() -> dict[str, Any]:
    """204 No Content."""
    return response(204, None)
