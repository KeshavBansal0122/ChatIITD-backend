"""Encrypt / decrypt user LLM API keys at rest (AES-256-GCM)."""

from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _key_material() -> bytes:
    raw = os.environ.get("CREDENTIALS_ENCRYPTION_KEY") or os.environ.get("JWT_SECRET")
    if not raw:
        raise RuntimeError("CREDENTIALS_ENCRYPTION_KEY (or JWT_SECRET) required to store API keys")
    # Derive 32-byte key
    return hashlib.sha256(raw.encode("utf-8")).digest()


def fingerprint_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


@dataclass
class EncryptedSecret:
    ciphertext: bytes
    nonce: bytes
    fingerprint: str


def encrypt_api_key(api_key: str) -> EncryptedSecret:
    nonce = secrets.token_bytes(12)
    ct = AESGCM(_key_material()).encrypt(nonce, api_key.encode("utf-8"), None)
    return EncryptedSecret(
        ciphertext=ct,
        nonce=nonce,
        fingerprint=fingerprint_api_key(api_key),
    )


def decrypt_api_key(ciphertext: bytes, nonce: bytes) -> str:
    pt = AESGCM(_key_material()).decrypt(nonce, ciphertext, None)
    return pt.decode("utf-8")
