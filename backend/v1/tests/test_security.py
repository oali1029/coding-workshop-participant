"""Tests for password hashing and token handling.

These cover the pieces of app/security.py that do not need the web layer:
the cryptographic primitives the whole authentication system rests on.
"""

import os
import time

import jwt
import pytest

from app import security
from app.errors import ForbiddenError, UnauthorizedError


class TestPasswordHashing:
    def test_hash_is_not_the_password(self):
        """The stored value must not contain the password anywhere in it."""
        hashed = security.hash_password("SuperSecret123")
        assert "SuperSecret123" not in hashed

    def test_correct_password_verifies(self):
        hashed = security.hash_password("SuperSecret123")
        assert security.verify_password("SuperSecret123", hashed) is True

    def test_wrong_password_rejected(self):
        hashed = security.hash_password("SuperSecret123")
        assert security.verify_password("supersecret123", hashed) is False
        assert security.verify_password("", hashed) is False

    def test_same_password_hashes_differently_each_time(self):
        """Proves a random salt is in use.

        If two hashes of the same password were identical, an attacker who
        obtained the database could spot users sharing a password and could
        pre-compute hashes of common passwords once for everybody.
        """
        assert security.hash_password("Repeated1") != security.hash_password("Repeated1")

    def test_stored_format_records_its_own_settings(self):
        """The algorithm and iteration count travel with each hash.

        This is what allows the iteration count to be raised in future without
        locking out users whose passwords were hashed under the old cost.
        """
        algorithm, iterations, salt, digest = security.hash_password("Whatever1").split("$")
        assert algorithm == "pbkdf2_sha256"
        assert int(iterations) >= 100_000
        assert len(salt) == 32  # 16 bytes as hex
        assert len(digest) == 64  # sha256 is 32 bytes as hex

    def test_malformed_hash_is_rejected_not_crashed(self):
        """Corrupt stored data must fail closed, never raise."""
        assert security.verify_password("anything", "not-a-real-hash") is False
        assert security.verify_password("anything", "") is False

    def test_dummy_hash_is_well_formed_and_unmatchable(self):
        """The constant used to equalise login timing must behave like a hash."""
        assert security.DUMMY_PASSWORD_HASH.startswith("pbkdf2_sha256$")
        assert security.verify_password("password", security.DUMMY_PASSWORD_HASH) is False


class TestTokens:
    def test_round_trip_preserves_identity_and_role(self):
        user = {"id": 42, "email": "someone@acme.inc", "role": security.ROLE_ENGINEER}
        claims = security.decode_access_token(security.create_access_token(user))

        assert claims["sub"] == "42"
        assert claims["email"] == "someone@acme.inc"
        assert claims["role"] == security.ROLE_ENGINEER

    def test_token_carries_an_expiry(self):
        user = {"id": 1, "email": "a@acme.inc", "role": security.ROLE_EMPLOYEE}
        claims = security.decode_access_token(security.create_access_token(user))

        assert claims["exp"] > time.time()

    def test_tampered_token_is_rejected(self):
        """The whole point of signing: altered contents must not be accepted."""
        user = {"id": 1, "email": "a@acme.inc", "role": security.ROLE_EMPLOYEE}
        token = security.create_access_token(user)

        # Flip a character in the payload section.
        header, payload, signature = token.split(".")
        altered = f"{header}.{payload[:-2]}XY.{signature}"

        with pytest.raises(UnauthorizedError):
            security.decode_access_token(altered)

    def test_token_signed_with_a_different_key_is_rejected(self):
        """Someone who forges a token without our key must get nowhere."""
        forged = jwt.encode(
            {"sub": "1", "role": security.ROLE_FACILITY_ADMIN},
            "an-attackers-own-key",
            algorithm="HS256",
        )
        with pytest.raises(UnauthorizedError):
            security.decode_access_token(forged)

    def test_expired_token_is_rejected(self):
        from datetime import datetime, timedelta, timezone

        expired = jwt.encode(
            {
                "sub": "1",
                "role": security.ROLE_EMPLOYEE,
                "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            },
            security.get_signing_key(),
            algorithm="HS256",
        )
        with pytest.raises(UnauthorizedError):
            security.decode_access_token(expired)

    def test_garbage_is_rejected(self):
        with pytest.raises(UnauthorizedError):
            security.decode_access_token("this is not a token")


class TestRoleChecks:
    def test_permitted_role_passes(self):
        user = {"id": 1, "role": security.ROLE_FACILITY_ADMIN}
        security.require_roles(user, frozenset({security.ROLE_FACILITY_ADMIN}))

    def test_wrong_role_is_forbidden(self):
        user = {"id": 1, "role": security.ROLE_EMPLOYEE}
        with pytest.raises(ForbiddenError):
            security.require_roles(user, frozenset({security.ROLE_FACILITY_ADMIN}))

    def test_any_authenticated_accepts_all_three_roles(self):
        for role in (
            security.ROLE_EMPLOYEE,
            security.ROLE_ENGINEER,
            security.ROLE_FACILITY_ADMIN,
        ):
            security.require_roles({"id": 1, "role": role}, security.ANY_AUTHENTICATED)


class TestEmailRules:
    @pytest.mark.parametrize(
        "email",
        ["person@acme.inc", "Person@ACME.inc", "  spaced@acme.inc  ", "a+tag@acme.inc"],
    )
    def test_acme_addresses_accepted(self, email):
        assert security.is_acme_email(email) is True

    @pytest.mark.parametrize(
        "email",
        [
            "person@gmail.com",
            "person@acme.com",
            "person@notacme.inc.evil.com",
            "person@acme.inc.attacker.com",
            "plainstring",
        ],
    )
    def test_non_acme_addresses_rejected(self, email):
        assert security.is_acme_email(email) is False

    def test_normalisation_makes_addresses_comparable(self):
        assert security.normalize_email("  Person@ACME.inc ") == "person@acme.inc"


class TestBootstrapAdminPassword:
    """The bootstrap admin password must come from the environment, never code."""

    def test_no_password_literal_exists_in_the_source(self):
        """Guards against anyone reintroducing a hardcoded credential.

        security.py may name the environment variable and the admin's email, but
        it must not contain the password itself.
        """
        import inspect

        source = inspect.getsource(security)

        assert "ChangeMe" not in source
        assert not hasattr(security, "SEED_ADMIN_PASSWORD")

    def test_reads_the_value_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "supplied-at-deploy-time")
        assert security.get_bootstrap_admin_password() == "supplied-at-deploy-time"

    def test_returns_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
        assert security.get_bootstrap_admin_password() is None

    def test_returns_none_when_blank_or_whitespace(self, monkeypatch):
        """A variable set to an empty string must count as "not provided".

        Shell scripts and Terraform both produce empty strings for unset values,
        so treating "" as a real password would seed an account with a blank one.
        """
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "")
        assert security.get_bootstrap_admin_password() is None

        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "   ")
        assert security.get_bootstrap_admin_password() is None

    def test_surrounding_whitespace_is_trimmed(self, monkeypatch):
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "  padded-value  ")
        assert security.get_bootstrap_admin_password() == "padded-value"


class TestBootstrapAdminSeeding:
    """These tests delete and recreate the administrator, so they restore it.

    Without the fixture below, whichever test ran last would leave the account
    either missing or holding an unexpected password, and any later test that
    signs in as the administrator would fail for an unrelated reason.
    """

    @pytest.fixture(autouse=True)
    def restore_admin_afterwards(self):
        import conftest

        from app import db, migrations

        yield

        db.execute("DELETE FROM users WHERE email = %s", (security.SEED_ADMIN_EMAIL,))
        os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = conftest.BOOTSTRAP_ADMIN_TEST_PASSWORD
        migrations.ensure_bootstrap_admin()

    def test_missing_password_skips_seeding_without_raising(self, monkeypatch):
        """A missing variable must not take the application down.

        Every endpoint, including the health check, would otherwise fail over an
        optional convenience account.
        """
        from app import db, migrations

        monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
        db.execute("DELETE FROM users WHERE email = %s", (security.SEED_ADMIN_EMAIL,))

        assert migrations.ensure_bootstrap_admin() is False

        row = db.query_one("SELECT id FROM users WHERE email = %s", (security.SEED_ADMIN_EMAIL,))
        assert row is None

    def test_seeding_creates_the_admin_once_and_does_not_reset_it(self, monkeypatch):
        """Re-running must leave an existing administrator untouched.

        Otherwise every deployment would silently reset the password to whatever
        the deployer's environment happened to hold, undoing any change the
        administrator had made.
        """
        from app import db, migrations

        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "first-password-value")
        db.execute("DELETE FROM users WHERE email = %s", (security.SEED_ADMIN_EMAIL,))

        assert migrations.ensure_bootstrap_admin() is True

        original = db.query_one(
            "SELECT password_hash, role FROM users WHERE email = %s",
            (security.SEED_ADMIN_EMAIL,),
        )
        assert original["role"] == security.ROLE_FACILITY_ADMIN
        assert security.verify_password("first-password-value", original["password_hash"])

        # A later deployment with a different value must change nothing.
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "second-password-value")
        assert migrations.ensure_bootstrap_admin() is False

        after = db.query_one(
            "SELECT password_hash FROM users WHERE email = %s",
            (security.SEED_ADMIN_EMAIL,),
        )
        assert after["password_hash"] == original["password_hash"]

    def test_password_is_stored_hashed(self, monkeypatch):
        from app import db, migrations

        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "hash-me-please")
        db.execute("DELETE FROM users WHERE email = %s", (security.SEED_ADMIN_EMAIL,))
        migrations.ensure_bootstrap_admin()

        row = db.query_one(
            "SELECT password_hash FROM users WHERE email = %s",
            (security.SEED_ADMIN_EMAIL,),
        )

        assert "hash-me-please" not in row["password_hash"]
        assert row["password_hash"].startswith("pbkdf2_sha256$")
