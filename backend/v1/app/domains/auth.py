"""Registration, login, and "who am I" — the authentication endpoints.

=============================================================================
WHAT THIS FILE IS RESPONSIBLE FOR
=============================================================================
The three endpoints that let a person get into the application:

    POST /api/v1/auth/register   create an account and sign straight in
    POST /api/v1/auth/login      exchange email + password for a token
    GET  /api/v1/auth/me         report who the current token belongs to

The cryptography itself is not here — it lives in app/security.py. This file
handles the product rules: who may register, what counts as valid input, and
what the API says back.

=============================================================================
THE COMPANY EMAIL RULE, AND WHY IT IS CHECKED THREE TIMES
=============================================================================
Only addresses ending in "@acme.inc" may register. That rule is enforced in
three independent places:

    1. The React form        — instant feedback while typing.
    2. This file             — the check that actually matters.
    3. A database CONSTRAINT — a final backstop (see migration 2).

The first is a convenience and nothing more. Anyone can bypass the browser
entirely and post directly to the API with `curl`, so a front-end check is a
usability feature, never a security control. Layer 2 is the real boundary.
Layer 3 protects against a future bug in layer 2.

=============================================================================
WHY SELF-REGISTRATION CANNOT CREATE AN ADMINISTRATOR
=============================================================================
`register` never reads a role from the request. The role is written as the
constant EMPLOYEE, so a request body containing `{"role": "FACILITY_ADMIN"}`
is silently ignored rather than honoured.

This is deliberate. Filtering out a role field would also work, but it depends
on remembering to filter — and a later change that starts copying fields from
the body in bulk would quietly reintroduce the hole. Never reading the value at
all means privilege escalation is impossible by construction, not by vigilance.

Elevated accounts therefore come from exactly two places: the administrator
seeded by migration 2, and (in a later slice) promotion by an existing admin.

=============================================================================
WHY LOGIN IS VAGUE ABOUT WHAT WENT WRONG
=============================================================================
A helpful error message is a gift to an attacker. "No account with that email"
confirms which addresses are registered, which is useful for targeting
phishing or password-stuffing. So a wrong email and a wrong password produce
the identical response, and `login` also does identical WORK in both cases —
see the dummy hash comment below.
"""

import logging
from typing import Any

from .. import db, security
from ..errors import ConflictError, UnauthorizedError, ValidationError
from ..http import Request, created, ok

logger = logging.getLogger(__name__)

# Long enough to resist casual guessing without pushing people towards writing
# passwords down. The upper bound is not about security: PBKDF2 hashes its
# input, so a very long password is not a risk — but an unbounded field lets
# someone post a megabyte of text and make the server do pointless work.
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 200

MAX_NAME_LENGTH = 120
MAX_EMAIL_LENGTH = 200


def _public_user(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a database row into the user shape the API is allowed to return.

    THIS FUNCTION IS A SECURITY BOUNDARY. A users row contains
    `password_hash`, which must never leave the server. Rather than remembering
    to delete that field at each of the several places a user is returned, every
    path goes through this one function that names the safe fields explicitly.

    Listing what to INCLUDE rather than what to exclude matters: if a future
    migration adds a sensitive column, an exclude-list would leak it by default,
    whereas this include-list simply will not mention it.

    Args:
        row: A row from the users table.

    Returns:
        A dictionary safe to serialise into an HTTP response.
    """
    return {
        "id": row["id"],
        "email": row["email"],
        "full_name": row["full_name"],
        "role": row["role"],
    }


def _require_text(body: dict[str, Any], field: str, max_length: int) -> str:
    """Pull a non-empty string out of the request body, or raise.

    Args:
        body: The decoded JSON body.
        field: Which key to read.
        max_length: Longest value accepted.

    Returns:
        The trimmed value.

    Raises:
        ValidationError: Missing, not a string, blank, or too long. The
            `details` field names the offending input so the React form can
            highlight the right box.
    """
    value = body.get(field)

    if not isinstance(value, str) or not value.strip():
        raise ValidationError(
            "This field is required.",
            details={"field": field},
        )

    value = value.strip()

    if len(value) > max_length:
        raise ValidationError(
            f"This field must be {max_length} characters or fewer.",
            details={"field": field},
        )

    return value


def register(request: Request) -> dict[str, Any]:
    """Create a new EMPLOYEE account and sign the person in.

    Flow:
        validate input -> enforce the @acme.inc rule -> hash the password
        -> insert -> issue a token.

    Args:
        request: Body must contain `full_name`, `email` and `password`. Any
            `role` present is ignored — see the module docstring.

    Returns:
        201 with `{token, user}`.

    Raises:
        ValidationError: Input missing, malformed, or the wrong email domain.
        ConflictError: The email address is already registered.
    """
    body = request.json_body()

    full_name = _require_text(body, "full_name", MAX_NAME_LENGTH)
    raw_email = _require_text(body, "email", MAX_EMAIL_LENGTH)
    password = body.get("password")

    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
            details={"field": "password"},
        )

    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValidationError(
            f"Password must be {MAX_PASSWORD_LENGTH} characters or fewer.",
            details={"field": "password"},
        )

    # THE REAL DOMAIN CHECK. The browser also checks, but this is the one that
    # cannot be bypassed.
    if not security.is_acme_email(raw_email):
        raise ValidationError(
            f"Registration is restricted to {security.ALLOWED_EMAIL_DOMAIN} email addresses.",
            details={"field": "email"},
        )

    # One canonical form, so "A@Acme.Inc" and "a@acme.inc" cannot become two
    # separate accounts.
    email = security.normalize_email(raw_email)

    # Hash before touching the database, so the plain password exists only as a
    # local variable and is never part of a query, a log line, or an error.
    password_hash = security.hash_password(password)

    # "ON CONFLICT (email) DO NOTHING" combined with "RETURNING" gives us an
    # atomic insert-or-detect-duplicate. Checking for an existing row first and
    # then inserting would leave a gap in which another request could insert the
    # same address — the database's UNIQUE constraint is the only thing that can
    # settle that race correctly.
    #
    # When the insert is skipped, RETURNING produces no row, which is how we
    # know the address was taken.
    row = db.query_one(
        """
        INSERT INTO users (email, password_hash, full_name, role)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (email) DO NOTHING
        RETURNING id, email, full_name, role, is_active, created_at
        """,
        (
            email,
            password_hash,
            full_name,
            # Hard-coded. Never taken from the request. See module docstring.
            security.ROLE_EMPLOYEE,
        ),
    )

    if row is None:
        raise ConflictError("An account with this email address already exists.")

    logger.info("Registered new user %s", row["id"])

    # Signing the person in immediately avoids making them type the password
    # again one second after choosing it. They have just proved they know it,
    # so there is nothing further to verify.
    token = security.create_access_token(row)

    return created({"token": token, "user": _public_user(row)})


def login(request: Request) -> dict[str, Any]:
    """Exchange an email and password for an access token.

    Args:
        request: Body must contain `email` and `password`.

    Returns:
        200 with `{token, user}`.

    Raises:
        UnauthorizedError: Wrong credentials, or a deactivated account.
    """
    body = request.json_body()

    raw_email = body.get("email")
    password = body.get("password")

    # Note this is 401, not 400. A login attempt with pieces missing is a failed
    # login, and answering "you forgot the password field" would distinguish
    # malformed attempts from wrong ones for anyone probing the endpoint.
    if not isinstance(raw_email, str) or not isinstance(password, str):
        raise UnauthorizedError("Invalid email or password.")

    email = security.normalize_email(raw_email)

    user = db.query_one(
        """
        SELECT id, email, password_hash, full_name, role, is_active, created_at
        FROM users
        WHERE email = %s
        """,
        (email,),
    )

    # TIMING: verify a throwaway hash when the account does not exist, so that
    # a request for an unknown address takes the same time as one for a real
    # address with the wrong password. Returning early here instead would make
    # "no such user" measurably faster and turn this endpoint into a way to
    # discover which employees have accounts.
    stored_hash = user["password_hash"] if user else security.DUMMY_PASSWORD_HASH
    password_matches = security.verify_password(password, stored_hash)

    if user is None or not password_matches:
        # ONE message for both failure modes. See the module docstring.
        logger.info("Failed login attempt for %s", email)
        raise UnauthorizedError("Invalid email or password.")

    if not user["is_active"]:
        # Distinct from the message above, and deliberately so: this is only
        # reachable after the correct password was supplied, so the account
        # holder already knows the account exists. Telling them it is disabled
        # is helpful and leaks nothing they did not already know.
        raise UnauthorizedError("This account has been deactivated.")

    logger.info("User %s signed in", user["id"])

    token = security.create_access_token(user)

    return ok({"token": token, "user": _public_user(user)})


def me(request: Request) -> dict[str, Any]:
    """Return the signed-in user's identity and role.

    The React app calls this on startup to restore a session: the browser has a
    token in local storage, but the user details are not stored alongside it, so
    this endpoint turns the token back into a name and a role.

    It also serves as the check that a stored token is still good. If it has
    expired, been tampered with, or belongs to a deactivated account, the
    router's authentication step raises 401 before this function runs, and the
    front end knows to show the login screen.

    Args:
        request: `request.user` has already been populated by the router. This
            endpoint does no authentication of its own — see app/router.py,
            where every protected route is handled identically.

    Returns:
        200 with `{user}`.
    """
    return ok({"user": _public_user(request.user)})
