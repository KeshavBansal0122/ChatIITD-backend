"""Rolling-window token quotas (prompt + completion)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import text

from .models import get_session


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class QuotaStatus:
    allowed: bool
    used: int
    limit: int
    remaining: int
    window_hours: float
    resets_at: Optional[datetime]
    byok: bool
    reason: str = ""


def quota_config(*, is_authenticated: bool) -> tuple[int, float]:
    window = _env_float("RATE_LIMIT_WINDOW_HOURS", 4.0)
    if is_authenticated:
        limit = _env_int("RATE_LIMIT_TOKENS", 10_000)
    else:
        # Strict guest / device limits
        limit = _env_int("RATE_LIMIT_GUEST_TOKENS", 1_500)
    return limit, window


def ensure_usage_tables() -> None:
    mig = (
        __import__("pathlib").Path(__file__).resolve().parent.parent
        / "db"
        / "migrations"
        / "003_llm_usage_and_credentials.sql"
    )
    if not mig.exists():
        return
    with get_session() as sess:
        sess.execute(text(mig.read_text(encoding="utf-8")))
        sess.commit()


def record_usage(
    *,
    user_id: Optional[int],
    device_fingerprint: Optional[str],
    provider: str,
    model: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    chat_id: Optional[int] = None,
) -> None:
    prompt_tokens = max(0, int(prompt_tokens or 0))
    completion_tokens = max(0, int(completion_tokens or 0))
    total = prompt_tokens + completion_tokens
    if total <= 0:
        return
    try:
        with get_session() as sess:
            sess.execute(
                text(
                    """
                    INSERT INTO llm_usage
                        (user_id, device_fingerprint, provider, model,
                         prompt_tokens, completion_tokens, total_tokens, chat_id)
                    VALUES
                        (:user_id, :fp, :provider, :model,
                         :pt, :ct, :tt, :chat_id)
                    """
                ),
                {
                    "user_id": user_id,
                    "fp": device_fingerprint,
                    "provider": provider,
                    "model": model,
                    "pt": prompt_tokens,
                    "ct": completion_tokens,
                    "tt": total,
                    "chat_id": chat_id,
                },
            )
            sess.commit()
    except Exception:
        # Never break the chat path on usage accounting failure
        import logging

        logging.getLogger(__name__).exception("record_usage failed")


def _sum_tokens(
    *,
    user_id: Optional[int],
    device_fingerprint: Optional[str],
    since: datetime,
) -> int:
    with get_session() as sess:
        if user_id is not None:
            row = sess.execute(
                text(
                    """
                    SELECT COALESCE(SUM(total_tokens), 0)::int
                    FROM llm_usage
                    WHERE user_id = :uid AND created_at >= :since
                    """
                ),
                {"uid": user_id, "since": since},
            ).first()
        else:
            row = sess.execute(
                text(
                    """
                    SELECT COALESCE(SUM(total_tokens), 0)::int
                    FROM llm_usage
                    WHERE device_fingerprint = :fp AND created_at >= :since
                    """
                ),
                {"fp": device_fingerprint, "since": since},
            ).first()
        return int(row[0] if row else 0)


def check_quota(
    *,
    user_id: Optional[int],
    device_fingerprint: Optional[str],
    has_byok: bool,
) -> QuotaStatus:
    if not _env_bool("RATE_LIMIT_ENABLED", True):
        return QuotaStatus(
            allowed=True,
            used=0,
            limit=0,
            remaining=0,
            window_hours=0,
            resets_at=None,
            byok=has_byok,
            reason="disabled",
        )

    if has_byok and _env_bool("RATE_LIMIT_BYOK_EXEMPT", True):
        return QuotaStatus(
            allowed=True,
            used=0,
            limit=0,
            remaining=0,
            window_hours=_env_float("RATE_LIMIT_WINDOW_HOURS", 4.0),
            resets_at=None,
            byok=True,
            reason="byok_exempt",
        )

    is_auth = user_id is not None
    limit, window_hours = quota_config(is_authenticated=is_auth)
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=window_hours)

    if not is_auth and not device_fingerprint:
        return QuotaStatus(
            allowed=False,
            used=0,
            limit=limit,
            remaining=0,
            window_hours=window_hours,
            resets_at=now + timedelta(hours=window_hours),
            byok=False,
            reason="missing_device",
        )

    used = _sum_tokens(
        user_id=user_id if is_auth else None,
        device_fingerprint=None if is_auth else device_fingerprint,
        since=since,
    )
    remaining = max(0, limit - used)
    allowed = used < limit
    return QuotaStatus(
        allowed=allowed,
        used=used,
        limit=limit,
        remaining=remaining,
        window_hours=window_hours,
        resets_at=since + timedelta(hours=window_hours) if not allowed else now + timedelta(hours=window_hours),
        byok=False,
        reason="ok" if allowed else "quota_exceeded",
    )
