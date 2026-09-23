"""Expected failures, and the HTTP status each one maps to.

Anything raised as an :class:`AppError` is a deliberate, safe-to-show outcome
and is returned to the client with its message intact. Anything else escaping a
handler is treated as a bug and becomes a generic 500, so internal details never
reach the browser. That split is why this module exists.

To add a new kind of failure, add a subclass with its own status and code.
"""

from typing import Any


class AppError(Exception):
    """Base class for failures reported to the caller.

    Args:
        message: Shown to the user, so it must not contain internal detail.
        details: Optional context, typically ``{"field": "email"}`` so a form
            can highlight the right input.
    """

    # Subclasses override these two.
    status: int = 400
    code: str = "bad_request"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Render as the JSON body sent to the client."""
        body: dict[str, Any] = {"error": self.code, "message": self.message}
        if self.details:
            body["details"] = self.details
        return body


class ValidationError(AppError):
    """Input was understood but unacceptable."""

    status = 400
    code = "validation_error"


class UnauthorizedError(AppError):
    """Caller has not proved who they are — missing or invalid token."""

    status = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    """Caller is known, but their role does not permit this action."""

    status = 403
    code = "forbidden"


class NotFoundError(AppError):
    """Resource does not exist, or is not visible to this caller.

    The second half matters: requesting someone else's record returns 404
    rather than 403, because answering "forbidden" would confirm it exists.
    """

    status = 404
    code = "not_found"


class MethodNotAllowedError(AppError):
    """The URL exists, but not for this HTTP method."""

    status = 405
    code = "method_not_allowed"


class ConflictError(AppError):
    """Request collides with existing state, e.g. a duplicate email."""

    status = 409
    code = "conflict"
