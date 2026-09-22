"""Passwords, login tokens, and permission checking.

=============================================================================
WHAT THIS FILE IS RESPONSIBLE FOR
=============================================================================
Everything to do with proving who a user is and what they are allowed to do.
It answers three separate questions that are easy to confuse:

    "Is this really the password?"   -> hash_password / verify_password
    "Who is making this request?"    -> authentication  (create/decode token)
    "Are they allowed to do this?"   -> authorization   (role checking)

Authentication and authorization are different, and the order matters: we must
know WHO someone is before we can decide WHAT they may do. The HTTP status
codes reflect the split — 401 means "I do not know who you are", 403 means
"I know exactly who you are, and the answer is no".

=============================================================================
PART 1: WHY WE HASH PASSWORDS INSTEAD OF STORING THEM
=============================================================================
We never store a password. If our database were ever copied, plain passwords
would let an attacker into every account — and, because people reuse
passwords, into their other accounts elsewhere too.

Instead we store a "hash": the result of a one-way mathematical function.
Running it forwards is easy, running it backwards is not feasible. To check a
login we hash what the user typed and compare it with the stored hash. We
never need the original back.

Two refinements make that genuinely safe:

  A SALT is random data mixed in, different for every user. Without it, two
  people with the same password would produce identical hashes — visible in
  the database — and an attacker could pre-compute hashes of common passwords
  once and look them all up. A per-user salt makes every stored hash unique
  and forces the attacker to start over for each account.

  MANY ITERATIONS. We repeat the hash 200,000 times. A legitimate login pays
  this cost once and barely notices. An attacker guessing millions of
  passwords pays it every single guess, which is what makes brute force
  impractical.

WHY PBKDF2 AND NOT BCRYPT OR ARGON2
Bcrypt and Argon2 are stronger choices in general and would be preferable on a
normal server. They are avoided here for a concrete deployment reason: both
are C extensions that must be compiled for the exact platform they run on.
This project packages the backend by copying installed libraries into a zip
file, so a library built for the developer's machine can fail to load inside
AWS Lambda — and it fails at import time, taking down every endpoint at once,
with an error that does not obviously point at the cause.

PBKDF2 ships inside Python's own standard library. There is nothing to
compile, nothing to package, and nothing that can mismatch. For a workshop
application it is a sound, widely used algorithm, and the reliability is worth
more here than the theoretical advantage of the alternatives.

=============================================================================
PART 2: HOW STAYING LOGGED IN WORKS (JWT)
=============================================================================
HTTP has no memory: each request arrives knowing nothing about the last one.
Something must carry "I already logged in" from one request to the next.

A traditional server stores a session in memory and gives the browser an id.
That does not fit this architecture: our backend is a Lambda that may be shut
down between any two requests, and AWS may run several copies at once. There
is no shared memory to keep sessions in.

So we use a JWT (JSON Web Token) instead. On successful login the server
builds a small block of JSON — who you are, your role, when it expires — and
signs it with a secret key. The browser sends that token back with every
request. The server re-checks the signature to confirm the contents have not
been altered, and no server-side storage is involved.

IMPORTANT AND OFTEN MISUNDERSTOOD: a JWT is signed, NOT encrypted. Anyone can
read its contents; the signature only proves nobody CHANGED them. A user could
read their own token and see `"role": "EMPLOYEE"`, and edit it to say
FACILITY_ADMIN — but they cannot produce a matching signature without the
secret key, so the server rejects it. The rule that follows: never put
anything secret inside a token.

WHERE THE SIGNING KEY LIVES
Every running copy of the Lambda must use the SAME key, or a token issued by
one copy would be rejected by another and users would be logged out at random.
It also has to survive redeployment. We therefore generate it once and store
it in the database, in the `app_config` table created by migration 1. See
`get_signing_key` below.
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

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
# The three kinds of user in the product. Defined as constants rather than
# loose strings so a typo like "EMPLOYE" fails immediately and visibly instead
# of silently granting nobody access.
ROLE_EMPLOYEE = "EMPLOYEE"
ROLE_ENGINEER = "ENGINEER"
ROLE_FACILITY_ADMIN = "FACILITY_ADMIN"

ALL_ROLES: frozenset[str] = frozenset({ROLE_EMPLOYEE, ROLE_ENGINEER, ROLE_FACILITY_ADMIN})

# Used by routes that any signed-in user may call, regardless of role.
ANY_AUTHENTICATED: frozenset[str] = ALL_ROLES

# Only this email domain may register. Enforced in three independent places —
# the React form, the backend, and a CHECK constraint on the database table.
# The frontend check is only a convenience for the user; anyone can bypass it
# by calling the API directly, which is exactly why the backend check is the
# one that actually matters.
ALLOWED_EMAIL_DOMAIN = "@acme.inc"

# ---------------------------------------------------------------------------
# Password hashing settings
# ---------------------------------------------------------------------------
_HASH_ALGORITHM = "sha256"
_HASH_ITERATIONS = 200_000
_SALT_BYTES = 16

# Stored hashes look like:
#   pbkdf2_sha256$200000$<salt hex>$<hash hex>
#
# The algorithm and iteration count are stored ALONGSIDE each hash rather than
# only in this file. That means the cost can be raised later — as computers get
# faster it should be — and existing users can still log in, because their old
# hashes carry the settings they were created with. Without this, raising
# _HASH_ITERATIONS would lock out every existing user.
_HASH_PREFIX = "pbkdf2_sha256"

# How long a login lasts before the user must sign in again. Short enough that
# a stolen token stops working reasonably soon, long enough to cover a working
# day without interrupting people.
TOKEN_LIFETIME_HOURS = 12

# The row in app_config that holds our signing key.
_SIGNING_KEY_NAME = "jwt_signing_key"

# Cached after the first read so we do not query the database on every single
# request. Safe to cache because the key never changes once created.
_SIGNING_KEY_CACHE: str | None = None


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Turn a plain password into a value that is safe to store.

    Args:
        password: The password exactly as the user typed it.

    Returns:
        A string containing the algorithm, iteration count, salt and hash,
        separated by "$". This whole string goes into the database; there is
        no separate salt column, because the salt is not a secret — it only
        needs to be unique and stored with its hash.
    """
    # A fresh random salt per user. `secrets` is used rather than `random`
    # because `random` is predictable by design and must never be used for
    # anything security related.
    salt = secrets.token_bytes(_SALT_BYTES)

    digest = hashlib.pbkdf2_hmac(
        _HASH_ALGORITHM,
        password.encode("utf-8"),
        salt,
        _HASH_ITERATIONS,
    )

    return f"{_HASH_PREFIX}${_HASH_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Check a typed password against a stored hash.

    Args:
        password: What the user just typed at the login form.
        stored: The value previously produced by `hash_password`.

    Returns:
        True when they match.
    """
    try:
        prefix, iterations_text, salt_hex, expected_hex = stored.split("$")
    except ValueError:
        # A malformed stored value means corrupt data, not a correct password.
        # Refuse the login rather than raising, so one bad row cannot be used
        # to probe for errors.
        logger.warning("Encountered a malformed password hash")
        return False

    if prefix != _HASH_PREFIX:
        return False

    # Re-hash using the SETTINGS FROM THE STORED VALUE, not the current module
    # constants. This is what lets the iteration count be raised safely later.
    candidate = hashlib.pbkdf2_hmac(
        _HASH_ALGORITHM,
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        int(iterations_text),
    )

    # `compare_digest` instead of `==`. A normal comparison stops at the first
    # differing byte, so it returns fractionally faster for a wrong guess that
    # shares a longer prefix with the real value. Measuring those tiny
    # differences over many attempts can leak the secret — a "timing attack".
    # `compare_digest` always takes the same time regardless of where the
    # difference is.
    return hmac.compare_digest(candidate.hex(), expected_hex)


# ---------------------------------------------------------------------------
# The signing key
# ---------------------------------------------------------------------------
def get_signing_key() -> str:
    """Fetch the secret used to sign and verify login tokens, creating it once.

    Stored in the database so that every copy of the Lambda shares one key.
    See the explanation in the module docstring for why neither a hard-coded
    value nor a per-process random value would work.

    Returns:
        The signing key.
    """
    global _SIGNING_KEY_CACHE

    if _SIGNING_KEY_CACHE is not None:
        return _SIGNING_KEY_CACHE

    row = db.query_one("SELECT value FROM app_config WHERE key = %s", (_SIGNING_KEY_NAME,))

    if row is None:
        # First ever start. Generate a key and store it.
        generated = secrets.token_urlsafe(48)

        # Several Lambda copies can reach this line at the same moment.
        # "ON CONFLICT DO NOTHING" means whoever arrives second silently does
        # not overwrite the first key — critical, because overwriting it would
        # instantly invalidate every token the first copy had already issued.
        db.execute(
            "INSERT INTO app_config (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
            (_SIGNING_KEY_NAME, generated),
        )

        # Re-read rather than trusting `generated`: if another copy won the
        # race, the stored key is theirs, and we must use the one that is
        # actually in the database.
        row = db.query_one("SELECT value FROM app_config WHERE key = %s", (_SIGNING_KEY_NAME,))

    if row is None:
        raise RuntimeError("Could not create or read the token signing key.")

    _SIGNING_KEY_CACHE = row["value"]
    return _SIGNING_KEY_CACHE


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
def create_access_token(user: dict[str, Any]) -> str:
    """Issue a signed login token for a user who has just proved their identity.

    Args:
        user: The user's database row.

    Returns:
        The encoded JWT string for the browser to store and send back.
    """
    now = datetime.now(timezone.utc)

    payload = {
        # "sub" (subject) is the standard claim for "who this token is about".
        # Stored as a string because the JWT specification requires it.
        "sub": str(user["id"]),
        "email": user["email"],
        # The role is included so it can be displayed immediately in the UI.
        # It is NOT trusted for permission decisions — see authenticate_request,
        # which re-reads the role from the database on every request.
        "role": user["role"],
        "iat": now,
        "exp": now + timedelta(hours=TOKEN_LIFETIME_HOURS),
    }

    return jwt.encode(payload, get_signing_key(), algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify a token's signature and expiry, and return its contents.

    Args:
        token: The raw token string from the Authorization header.

    Returns:
        The decoded claims.

    Raises:
        UnauthorizedError: If the token is expired, tampered with, or not a
            token at all. All three produce the SAME message deliberately: a
            more specific error would help an attacker work out which part of
            a forged token to adjust next.
    """
    try:
        return jwt.decode(
            token,
            get_signing_key(),
            # Pinning the algorithm is a real security control, not a
            # formality. Historically, JWT libraries could be tricked by a
            # token whose header claimed algorithm "none", which made them skip
            # signature checking entirely. Naming the accepted algorithm here
            # means a token asking for anything else is rejected outright.
            algorithms=["HS256"],
        )
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("Your session has expired. Please sign in again.")
    except jwt.InvalidTokenError:
        raise UnauthorizedError("Invalid authentication token.")


# ---------------------------------------------------------------------------
# Authentication and authorization for a request
# ---------------------------------------------------------------------------
def authenticate_request(request: Any) -> dict[str, Any]:
    """Work out which user is making this request.

    Reads the standard HTTP header:

        Authorization: Bearer <token>

    Args:
        request: The incoming app.http.Request.

    Returns:
        The user's current database row.

    Raises:
        UnauthorizedError: No usable token, or the user no longer exists or
            has been deactivated.
    """
    header = request.header("authorization")

    if not header:
        raise UnauthorizedError("Authentication required.")

    # The "Bearer " prefix is the convention defined by the HTTP
    # specification; "bearer" meaning simply that whoever holds the token may
    # use it. Split on whitespace rather than slicing a fixed length, so odd
    # spacing from a client does not break the parse.
    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise UnauthorizedError("Authorization header must be in the form 'Bearer <token>'.")

    claims = decode_access_token(parts[1])

    try:
        user_id = int(claims["sub"])
    except (KeyError, TypeError, ValueError):
        raise UnauthorizedError("Invalid authentication token.")

    # DELIBERATE DESIGN DECISION: we look the user up in the database on every
    # authenticated request rather than trusting the role inside the token.
    #
    # The token is tamper-proof, so trusting it would be safe against forgery
    # — but it would be STALE. A token is valid for twelve hours, so if an
    # administrator changes someone's role or deactivates a leaver, the old
    # token would keep its old powers until it expired. Re-reading makes both
    # changes take effect on the very next request.
    #
    # The cost is one lookup by primary key, which is about the cheapest query
    # a database can perform. Correctness is worth far more than that here.
    user = db.query_one(
        """
        SELECT id, email, full_name, role, is_active, created_at
        FROM users
        WHERE id = %s
        """,
        (user_id,),
    )

    if user is None:
        # The token is validly signed but its user has since been deleted.
        raise UnauthorizedError("Invalid authentication token.")

    if not user["is_active"]:
        raise UnauthorizedError("This account has been deactivated.")

    return user


def require_roles(user: dict[str, Any], allowed: frozenset[str]) -> None:
    """Confirm a user holds one of the roles permitted for an endpoint.

    This is the single place role checks happen. Centralising it means a new
    endpoint cannot accidentally ship without a permission check — the route
    table has to state who may call it, and the router applies that here.

    Args:
        user: The authenticated user's row.
        allowed: The roles this endpoint accepts.

    Raises:
        ForbiddenError: The user is known, but their role is not on the list.
    """
    if user["role"] not in allowed:
        # Logged so that repeated permission failures are visible, which can
        # indicate either a UI bug showing buttons it should not, or someone
        # probing the API.
        logger.warning(
            "User %s with role %s was refused an endpoint requiring %s",
            user["id"],
            user["role"],
            sorted(allowed),
        )
        raise ForbiddenError("You do not have permission to perform this action.")


def is_acme_email(email: str) -> bool:
    """Check that an address belongs to the company domain.

    Lower-cased first so that "Someone@ACME.inc" is accepted — email domains
    are case-insensitive, and rejecting a capitalised address would be a
    confusing bug rather than a security measure.
    """
    return email.strip().lower().endswith(ALLOWED_EMAIL_DOMAIN)


def normalize_email(email: str) -> str:
    """Convert an address to the single canonical form we store and compare.

    Everything is lower-cased and trimmed on the way in, so "A@acme.inc" and
    "a@acme.inc " are recognised as the same account. Doing this once at the
    edge means every later comparison is a plain equality check, and the
    database's UNIQUE constraint on the column is enough to guarantee one
    account per person.
    """
    return email.strip().lower()


# ---------------------------------------------------------------------------
# The bootstrap administrator
# ---------------------------------------------------------------------------
# The application needs at least one FACILITY_ADMIN to exist, because
# self-registration only ever creates EMPLOYEE accounts — by design, so nobody
# can grant themselves privileges. Without a seeded admin there would be no way
# to ever have one.
#
# The email and display name are not secret, so they live here as constants.
# THE PASSWORD DOES NOT. It is read at runtime from an environment variable so
# that no real credential is ever written into source code, into a committed
# file, or into git history — where it would remain readable forever, even
# after being "changed", by anyone who can see the repository.
SEED_ADMIN_EMAIL = "admin@acme.inc"
SEED_ADMIN_NAME = "ACME Facility Administrator"

#: Name of the environment variable holding the bootstrap admin's password.
BOOTSTRAP_ADMIN_PASSWORD_VAR = "BOOTSTRAP_ADMIN_PASSWORD"


def get_bootstrap_admin_password() -> str | None:
    """Read the bootstrap administrator's password from the environment.

    The value is supplied by whoever deploys the application and never appears
    in the repository. See the deployment notes in the project README for how it
    is provided locally and on AWS.

    Returns:
        The password, or None when the variable is unset or blank. None is a
        supported, non-fatal outcome: the application starts normally and simply
        does not create the administrator. That is deliberate — refusing to boot
        would take down every endpoint, including the health check, over a
        missing convenience account.

    Note:
        The returned value is never logged and never included in an API
        response. The only thing done with it is hashing.
    """
    value = os.getenv(BOOTSTRAP_ADMIN_PASSWORD_VAR, "").strip()
    return value or None

# A correctly-formatted hash of a password nobody knows.
#
# The login handler verifies THIS when the submitted email does not exist, so
# that a request for a non-existent account performs the same expensive PBKDF2
# work as a request for a real one. Without it, "no such user" would return
# noticeably faster than "wrong password", and an attacker could time requests
# to discover which email addresses have accounts.
#
# Written as a literal rather than computed with hash_password() on purpose:
# module-level code runs on every Lambda cold start, and 200,000 PBKDF2
# iterations there would add roughly a quarter of a second to the first request
# for no benefit. The value is not a secret — it only has to be well-formed and
# impossible to match.
DUMMY_PASSWORD_HASH = (
    "pbkdf2_sha256$200000$"
    "9f2c41a7b8d3e5061c7a4b9e2f8d3a15$"
    "7d41e9b2c8a5f3061d9e4b7a2c8f5d310e6b9a4c7f2d85b1e3a9c6f4d827b50e"
)
