"""Password hashing, login tokens, and role checks.

Three related but distinct concerns live here: verifying a password,
establishing *who* is calling (authentication, 401 when it fails), and deciding
whether they may act (authorization, 403 when it fails).

Password hashing uses PBKDF2-HMAC-SHA256 from the standard library rather than
bcrypt or argon2. Those are stronger in principle, but both are compiled C
extensions, and this project packages the backend by zipping locally-installed
libraries — a wheel built for the developer's machine can fail to import inside
Lambda, taking down every endpoint at once. PBKDF2 has nothing to compile and
nothing to mismatch.

Sessions use signed JWTs because there is nowhere to keep server-side state:
Lambda may stop between requests and may run several copies at once. Note that
a JWT is signed, not encrypted — its contents are readable by anyone holding
it, so nothing secret goes inside one. The signature only proves the contents
were not altered.
"""

import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from . import db
from .errors import ForbiddenError, UnauthorizedError

logger = logging.getLogger(__name__)

ROLE_EMPLOYEE = "EMPLOYEE"
ROLE_ENGINEER = "ENGINEER"
ROLE_FACILITY_ADMIN = "FACILITY_ADMIN"

ALL_ROLES: frozenset[str] = frozenset({ROLE_EMPLOYEE, ROLE_ENGINEER, ROLE_FACILITY_ADMIN})

#: For routes any signed-in user may call, whatever their role.
#
#: Roles are additive rather than exclusive: an Engineer is an employee with
#: extra capabilities, not a separate kind of person. So employee-level routes
#: list every role, and an engineer- or admin-only route simply lists fewer.
#: Adding a capability never removes one.
ANY_AUTHENTICATED: frozenset[str] = ALL_ROLES

#: For routes only a Facility Admin may call.
FACILITY_ADMIN_ONLY: frozenset[str] = frozenset({ROLE_FACILITY_ADMIN})

#: Only this domain may self-register. Enforced here, in the React form, and by
#: a CHECK constraint on the users table. The form check is convenience only —
#: anyone can call the API directly, which is why the backend check is the real
#: boundary.
ALLOWED_EMAIL_DOMAIN = "@acme.inc"

_HASH_ALGORITHM = "sha256"
_HASH_ITERATIONS = 200_000
_SALT_BYTES = 16
_HASH_PREFIX = "pbkdf2_sha256"

TOKEN_LIFETIME_HOURS = 12

_SIGNING_KEY_NAME = "jwt_signing_key"
_SIGNING_KEY_CACHE: str | None = None


def hash_password(password: str) -> str:
    """Hash a password for storage.

    Returns ``pbkdf2_sha256$iterations$salt$hash``. The salt is random per user,
    so identical passwords do not produce identical hashes and an attacker
    cannot pre-compute one table for everybody. The iteration count is stored
    alongside each hash so it can be raised later without locking out existing
    users, whose hashes carry the cost they were created with.
    """
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        _HASH_ALGORITHM, password.encode("utf-8"), salt, _HASH_ITERATIONS
    )
    return f"{_HASH_PREFIX}${_HASH_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Check a password against a stored hash."""
    try:
        prefix, iterations_text, salt_hex, expected_hex = stored.split("$")
    except ValueError:
        # Corrupt stored data is not a correct password. Fail closed rather
        # than raising, so one bad row cannot be used to probe for errors.
        logger.warning("Encountered a malformed password hash")
        return False

    if prefix != _HASH_PREFIX:
        return False

    # Re-hash using the settings recorded in the stored value, not the current
    # module constants — this is what makes raising the cost safe.
    candidate = hashlib.pbkdf2_hmac(
        _HASH_ALGORITHM,
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        int(iterations_text),
    )

    # compare_digest takes constant time. A plain `==` returns fractionally
    # sooner for a wrong guess sharing a longer prefix, which is measurable
    # over many attempts.
    return hmac.compare_digest(candidate.hex(), expected_hex)


def get_signing_key() -> str:
    """Return the JWT signing key, generating and storing it on first use.

    Kept in the database because every Lambda copy must use the same key — a
    token issued by one has to be accepted by the others — and it must survive
    redeployment.
    """
    global _SIGNING_KEY_CACHE

    if _SIGNING_KEY_CACHE is not None:
        return _SIGNING_KEY_CACHE

    row = db.query_one("SELECT value FROM app_config WHERE key = %s", (_SIGNING_KEY_NAME,))

    if row is None:
        # Several copies can reach this simultaneously. DO NOTHING means the
        # loser does not overwrite the winner's key, which would instantly
        # invalidate any token already issued; re-reading picks up whichever
        # key actually landed.
        db.execute(
            "INSERT INTO app_config (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
            (_SIGNING_KEY_NAME, secrets.token_urlsafe(48)),
        )
        row = db.query_one("SELECT value FROM app_config WHERE key = %s", (_SIGNING_KEY_NAME,))

    if row is None:
        raise RuntimeError("Could not create or read the token signing key.")

    _SIGNING_KEY_CACHE = row["value"]
    return _SIGNING_KEY_CACHE


def create_access_token(user: dict[str, Any]) -> str:
    """Issue a signed token for a user who has proved their identity."""
    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(user["id"]),
        "email": user["email"],
        # Included so the UI can show the role immediately. It is NOT trusted
        # for permission decisions; authenticate_request re-reads it.
        "role": user["role"],
        "iat": now,
        "exp": now + timedelta(hours=TOKEN_LIFETIME_HOURS),
    }

    return jwt.encode(payload, get_signing_key(), algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify a token and return its claims.

    Expired, forged and malformed tokens all raise the same error: a more
    specific message would tell an attacker which part of a forgery to fix.
    """
    try:
        return jwt.decode(
            token,
            get_signing_key(),
            # Pinning the algorithm is a real control. Some JWT libraries could
            # historically be tricked by a token claiming algorithm "none",
            # which skipped signature verification entirely.
            algorithms=["HS256"],
        )
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("Your session has expired. Please sign in again.")
    except jwt.InvalidTokenError:
        raise UnauthorizedError("Invalid authentication token.")


def authenticate_request(request: Any) -> dict[str, Any]:
    """Identify the caller from the ``Authorization: Bearer <token>`` header.

    Returns the user's current database row.

    Raises:
        UnauthorizedError: No usable token, or the user is gone or deactivated.
    """
    header = request.header("authorization")

    if not header:
        raise UnauthorizedError("Authentication required.")

    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise UnauthorizedError("Authorization header must be in the form 'Bearer <token>'.")

    claims = decode_access_token(parts[1])

    try:
        user_id = int(claims["sub"])
    except (KeyError, TypeError, ValueError):
        raise UnauthorizedError("Invalid authentication token.")

    # The role is re-read here rather than taken from the token. The token is
    # tamper-proof but stale: it lives for twelve hours, so trusting it would
    # let a deactivated leaver or a demoted user keep their old access until it
    # expired. One primary-key lookup is a cheap price for that.
    user = db.query_one(
        "SELECT id, email, full_name, role, is_active, created_at FROM users WHERE id = %s",
        (user_id,),
    )

    if user is None:
        raise UnauthorizedError("Invalid authentication token.")

    if not user["is_active"]:
        raise UnauthorizedError("This account has been deactivated.")

    return user


def require_roles(user: dict[str, Any], allowed: frozenset[str]) -> None:
    """Confirm the user holds one of the roles an endpoint permits.

    The single place role checks happen, so a new endpoint cannot ship without
    one — the route table has to declare its rule and the router applies it here.
    """
    if user["role"] not in allowed:
        # Logged because repeated failures indicate either a UI showing buttons
        # it should not, or someone probing the API.
        logger.warning(
            "User %s with role %s was refused an endpoint requiring %s",
            user["id"],
            user["role"],
            sorted(allowed),
        )
        raise ForbiddenError("You do not have permission to perform this action.")


def is_acme_email(email: str) -> bool:
    """Whether an address belongs to the company domain."""
    return email.strip().lower().endswith(ALLOWED_EMAIL_DOMAIN)


def normalize_email(email: str) -> str:
    """Canonical form for storage and comparison.

    Lower-casing and trimming once on the way in means every later comparison
    is plain equality, and the UNIQUE constraint guarantees one account per
    person rather than one per capitalisation.
    """
    return email.strip().lower()


# The bootstrap administrator. Self-registration only ever creates EMPLOYEE
# accounts, so without a seeded admin no FACILITY_ADMIN could ever exist.
# Email and name are not secret; the password deliberately is not here.
SEED_ADMIN_EMAIL = "admin@acme.inc"
SEED_ADMIN_NAME = "ACME Facility Administrator"

BOOTSTRAP_ADMIN_PASSWORD_VAR = "BOOTSTRAP_ADMIN_PASSWORD"


def get_bootstrap_admin_password() -> str | None:
    """Read the bootstrap administrator's password from the environment.

    Supplied by whoever deploys the application so no real credential is ever
    committed, where git history would preserve it permanently.

    Returns None when unset or blank. That is a supported outcome: the
    application runs normally and skips creating the account, because refusing
    to start would take down every endpoint over an optional convenience
    account. Empty strings count as unset, since Terraform and shell scripts
    both produce "" for unset values.
    """
    return os.getenv(BOOTSTRAP_ADMIN_PASSWORD_VAR, "").strip() or None


# Verified by the login handler when an email does not exist, so that a request
# for an unknown address costs the same PBKDF2 work as a real one and cannot be
# timed to discover which employees have accounts. A literal rather than a
# computed value because module-level code runs on every cold start; it is not
# secret, it only has to be well-formed and unmatchable.
DUMMY_PASSWORD_HASH = (
    "pbkdf2_sha256$200000$"
    "9f2c41a7b8d3e5061c7a4b9e2f8d3a15$"
    "7d41e9b2c8a5f3061d9e4b7a2c8f5d310e6b9a4c7f2d85b1e3a9c6f4d827b50e"
)
