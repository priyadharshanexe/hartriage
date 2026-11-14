"""Passwords (argon2id), access tokens (JWT), opaque tokens and encryption at rest."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from hartriage.core.config import Settings

_hasher = PasswordHasher()  # argon2id with the library's current recommended parameters


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


# A real hash of a random password, so a login for an unknown email costs the same time.
DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def create_access_token(settings: Settings, user_id: uuid.UUID, org_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "org": str(org_id),
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_token_ttl_seconds)).timestamp()),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def decode_access_token(settings: Settings, token: str) -> dict[str, Any]:
    claims: dict[str, Any] = jwt.decode(
        token, settings.jwt_secret, algorithms=["HS256"], options={"require": ["exp", "sub", "org"]}
    )
    if claims.get("typ") != "access":
        raise jwt.InvalidTokenError("not an access token")
    return claims


class Cipher:
    """AES-256-GCM with a version prefix, so the key can be rotated later."""

    VERSION = "v1"

    def __init__(self, key: bytes) -> None:
        self._aes = AESGCM(key)

    def encrypt(self, plaintext: str, context: str = "") -> str:
        nonce = os.urandom(12)
        data = self._aes.encrypt(nonce, plaintext.encode(), context.encode() or None)
        return f"{self.VERSION}:{base64.b64encode(nonce + data).decode()}"

    def decrypt(self, token: str, context: str = "") -> str:
        version, _, payload = token.partition(":")
        if version != self.VERSION:
            raise ValueError("unknown encryption version")
        raw = base64.b64decode(payload)
        return self._aes.decrypt(raw[:12], raw[12:], context.encode() or None).decode()
