"""Registration, login, and current-user endpoints.

The cryptography lives in ``app.security``; this module holds the product
rules — who may register, what input is valid, and what the API says back.

Two decisions worth knowing:

*Self-registration cannot create a privileged account.* ``register`` never
reads a role from the request; it writes the EMPLOYEE constant, so a body
containing ``{"role": "FACILITY_ADMIN"}`` is ignored rather than honoured.
Filtering the field out would also work, but depends on remembering to filter —
never reading it makes escalation impossible by construction.

*Login is vague on purpose.* A wrong password and an unknown address produce an
identical response, and identical work, so the endpoint cannot be used to
discover which employees have accounts.
"""

import logging
from typing import Any

from .. import db, security
from ..errors import ConflictError, UnauthorizedError, ValidationError
from ..http import Request, created, ok, require_text

logger = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 8
# Not a security limit — PBKDF2 hashes any length. It stops someone posting a
# megabyte of text and making the server do pointless work.
MAX_PASSWORD_LENGTH = 200

MAX_NAME_LENGTH = 120
MAX_EMAIL_LENGTH = 200


def _public_user(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a users row into the shape the API may return.

    A security boundary: user rows contain ``password_hash``, which must never
    leave the server. Every path returning a user goes through here, and the
    fields are listed by inclusion — an exclusion list would leak any sensitive
    column added by a future migration.
    """
    return {
        "id": row["id"],
        "email": row["email"],
        "full_name": row["full_name"],
        "role": row["role"],
    }


def register(request: Request) -> dict[str, Any]:
    """Create an EMPLOYEE account and sign the person in.

    Returns 201 with ``{token, user}``.

    Raises:
        ValidationError: invalid input or a non-company email address.
        ConflictError: the address is already registered.
    """
    body = request.json_body()

    full_name = require_text(body, "full_name", MAX_NAME_LENGTH)
    raw_email = require_text(body, "email", MAX_EMAIL_LENGTH)
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

    # The React form checks this too, but that check is bypassable; this one is
    # the actual boundary.
    if not security.is_acme_email(raw_email):
        raise ValidationError(
            f"Registration is restricted to {security.ALLOWED_EMAIL_DOMAIN} email addresses.",
            details={"field": "email"},
        )

    email = security.normalize_email(raw_email)

    # Hash before touching the database so the plain password is never part of
    # a query, a log line, or an error.
    password_hash = security.hash_password(password)

    # ON CONFLICT with RETURNING makes insert-or-detect-duplicate atomic.
    # Checking for an existing row first would leave a gap in which another
    # request could insert the same address; only the UNIQUE constraint can
    # settle that race. No row returned means the address was taken.
    row = db.query_one(
        """
        INSERT INTO users (email, password_hash, full_name, role)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (email) DO NOTHING
        RETURNING id, email, full_name, role, is_active, created_at
        """,
        (email, password_hash, full_name, security.ROLE_EMPLOYEE),
    )

    if row is None:
        raise ConflictError("An account with this email address already exists.")

    logger.info("Registered new user %s", row["id"])

    # Signing in immediately: they have just proved they know the password, so
    # there is nothing further to verify.
    token = security.create_access_token(row)

    return created({"token": token, "user": _public_user(row)})


def login(request: Request) -> dict[str, Any]:
    """Exchange email and password for an access token.

    Returns 200 with ``{token, user}``.
    """
    body = request.json_body()

    raw_email = body.get("email")
    password = body.get("password")

    # 401 rather than 400: a malformed attempt is still a failed login, and
    # distinguishing the two would help someone probing the endpoint.
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

    # Verify a throwaway hash when the account does not exist, so an unknown
    # address costs the same time as a real one. Returning early instead would
    # make "no such user" measurably faster and turn this into a way to
    # enumerate employees.
    stored_hash = user["password_hash"] if user else security.DUMMY_PASSWORD_HASH
    password_matches = security.verify_password(password, stored_hash)

    if user is None or not password_matches:
        logger.info("Failed login attempt for %s", email)
        raise UnauthorizedError("Invalid email or password.")

    if not user["is_active"]:
        # A distinct message is safe here: it is only reachable after the
        # correct password, so the holder already knows the account exists.
        raise UnauthorizedError("This account has been deactivated.")

    logger.info("User %s signed in", user["id"])

    return ok({"token": security.create_access_token(user), "user": _public_user(user)})


def me(request: Request) -> dict[str, Any]:
    """Return the signed-in user's identity and role.

    The frontend calls this on startup to turn a stored token back into a name
    and role, and to confirm the token is still valid — if it is not, the
    router raises 401 before this runs.

    ``request.user`` is populated by the router; this handler performs no
    authentication of its own.
    """
    return ok({"user": _public_user(request.user)})
