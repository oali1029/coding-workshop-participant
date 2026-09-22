"""Expected failures, and the HTTP status code each one becomes.

=============================================================================
WHAT THIS FILE IS RESPONSIBLE FOR
=============================================================================
Things go wrong in predictable ways: a user asks for an incident that does not
exist, submits a form with a blank title, or tries to do something their role
does not allow. Those are not bugs — they are normal outcomes that the browser
needs to be told about clearly.

This file defines one exception class per kind of expected failure. Any code
in the application can "raise" one of these from anywhere, and the Lambda
entry point (../function.py) catches it in a single place and turns it into a
proper HTTP response.

=============================================================================
WHY DO IT THIS WAY
=============================================================================
Without this, every function would have to return something like
(data, error_code) and every caller would have to check it, forwarding errors
upward by hand. That clutters the code and it is easy to forget a check.

Raising an exception lets a function deep inside the call stack abandon its
work immediately and trust that one handler at the top will format the reply.

There is also a SECURITY reason for the split. Only errors defined here are
shown to the user. Anything else — a typo in our SQL, a network failure — is
an unexpected crash, and ../function.py deliberately replies with a generic
"internal error" message instead. That prevents leaking database structure or
file paths to whoever is poking at the API.
"""

from typing import Any


class AppError(Exception):
    """Base class for every failure we intend to show the user.

    Subclasses below set `status` and `code` to sensible defaults so that
    raising an error is usually a one-liner, for example:

        raise NotFoundError("Incident not found.")

    Args:
        message: Human-readable explanation. This IS shown to the user, so it
            must never contain internal details like SQL or stack traces.
        status: HTTP status code. Defaults to the subclass's value.
        code: Short machine-readable label, e.g. "not_found". The React app
            can branch on this without having to match English text, which
            matters because the text may change.
        details: Optional extra context, typically which fields failed
            validation, so a form can highlight the right input boxes.
    """

    # These are class-level defaults. Each subclass overrides them, and an
    # individual raise can still override them per-call via the arguments.
    status: int = 400
    code: str = "bad_request"

    def __init__(
        self,
        message: str,
        status: int | None = None,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message

        # Only overwrite the class default when the caller actually supplied a
        # value. Checking "is not None" rather than truthiness matters because
        # 0 is a valid-looking integer we would otherwise silently ignore.
        if status is not None:
            self.status = status
        if code is not None:
            self.code = code

        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Build the JSON body that the browser will receive.

        Every error in this API comes back in the same shape, which means the
        React app needs only one piece of error-handling code:

            {"error": "not_found", "message": "Incident not found."}

        Returns:
            A dictionary ready to be serialised to JSON. "details" is omitted
            entirely when empty, to keep responses tidy.
        """
        body: dict[str, Any] = {"error": self.code, "message": self.message}
        if self.details:
            body["details"] = self.details
        return body


class ValidationError(AppError):
    """The request was understood but the data in it was unacceptable.

    Raised when a required field is missing, a title is too long, or a status
    value is not one we recognise. 400 tells the client: "you sent this, and
    it was wrong — fix it and try again."
    """

    status = 400
    code = "validation_error"


class UnauthorizedError(AppError):
    """We do not know who is making this request.

    Raised when the login token is missing, expired, or unreadable. Despite
    the confusing historical name, HTTP 401 means "unauthenticated" — you have
    not proven who you are. The React app reacts to this by sending the user
    back to the login page.
    """

    status = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    """We know who you are, and you are not allowed to do this.

    Raised when, for example, an Employee tries to assign a ticket to an
    engineer — an action reserved for Facility Admins. The distinction from
    401 matters: logging in again will not help, so the React app shows a
    permission message instead of a login screen.
    """

    status = 403
    code = "forbidden"


class NotFoundError(AppError):
    """The requested thing does not exist, or is not visible to this user.

    Note the second half of that sentence. When an Employee requests someone
    else's incident we deliberately answer 404 rather than 403. Answering
    "forbidden" would confirm that the incident exists, which leaks
    information; 404 reveals nothing.
    """

    status = 404
    code = "not_found"


class ConflictError(AppError):
    """The request clashes with data that already exists.

    The common case is registering an email address that is already taken.
    The request was well-formed, so 400 would be misleading; the problem is
    the current state of the database.
    """

    status = 409
    code = "conflict"
