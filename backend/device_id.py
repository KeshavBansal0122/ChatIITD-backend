"""
Device identity for guest / abuse quotas.

Browsers cannot expose MAC addresses. Instead we issue a server-signed
HttpOnly cookie. Clients cannot forge a valid device id without the
server HMAC secret (spoofing the cookie value alone fails verification).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass

from fastapi import Request, Response

COOKIE_NAME = "chatiitd_did"
COOKIE_MAX_AGE = 60 * 60 * 24 * 400  # ~400 days


def _signing_secret() -> bytes:
    raw = os.environ.get("DEVICE_ID_SECRET") or os.environ.get("JWT_SECRET") or "dev-device-secret"
    return raw.encode("utf-8")


def _sign(payload: str) -> str:
    return hmac.new(_signing_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def mint_device_id() -> str:
    """Return opaque id: {random}.{ts}.{sig}"""
    rnd = secrets.token_urlsafe(24)
    ts = str(int(time.time()))
    body = f"{rnd}.{ts}"
    return f"{body}.{_sign(body)}"


def verify_device_id(token: str | None) -> str | None:
    if not token or token.count(".") != 2:
        return None
    rnd, ts, sig = token.split(".", 2)
    body = f"{rnd}.{ts}"
    expected = _sign(body)
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        int(ts)
    except ValueError:
        return None
    return token


def device_fingerprint_hash(device_id: str) -> str:
    """Stable hash stored in DB (not the raw cookie)."""
    return hashlib.sha256(f"did:{device_id}".encode()).hexdigest()


@dataclass
class DeviceContext:
    device_id: str
    fingerprint: str
    is_new: bool


def ensure_device_cookie(request: Request, response: Response | None = None) -> DeviceContext:
    """
    Read/verify device cookie; mint a new one if missing/invalid.
    If response is provided, set the cookie on it.
    """
    raw = request.cookies.get(COOKIE_NAME)
    verified = verify_device_id(raw)
    is_new = verified is None
    device_id = verified or mint_device_id()
    ctx = DeviceContext(
        device_id=device_id,
        fingerprint=device_fingerprint_hash(device_id),
        is_new=is_new,
    )
    if response is not None:
        attach_device_cookie(response, ctx)
    return ctx


def attach_device_cookie(response: Response, ctx: DeviceContext) -> None:
    """Always re-attach so max-age refreshes; value is server-signed."""
    secure = os.environ.get("COOKIE_SECURE", "true").lower() != "false"
    response.set_cookie(
        key=COOKIE_NAME,
        value=ctx.device_id,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
