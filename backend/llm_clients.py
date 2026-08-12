"""Resolve LLM clients: shared OpenRouter vs per-user BYOK (OpenAI-compat + Anthropic)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from openai import AsyncOpenAI, OpenAI
from sqlmodel import text

from .models import get_session
from .secrets_crypto import decrypt_api_key, encrypt_api_key

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
DEFAULT_MODEL = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-haiku-4.5")
OPENROUTER_BASE = "https://openrouter.ai/api/v1"

_OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://chatiitd.devclub.in",
    "X-OpenRouter-Title": "ChatIITD Academic Assistant",
}

PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4.1-mini",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-haiku-4-5-20251001",
    },
    "openrouter": {
        "base_url": OPENROUTER_BASE,
        "default_model": DEFAULT_MODEL,
    },
    "google": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-2.0-flash",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
    },
    "custom": {
        "base_url": "",
        "default_model": "",
    },
}


@dataclass
class LlmRuntime:
    provider: str
    model: str
    sync_client: Any
    async_client: Any
    extra_headers: dict
    is_byok: bool
    # "openai" | "anthropic" — which SDK path to use for chat completions
    sdk: str = "openai"


def shared_openrouter_runtime() -> LlmRuntime:
    return LlmRuntime(
        provider="openrouter",
        model=DEFAULT_MODEL,
        sync_client=OpenAI(base_url=OPENROUTER_BASE, api_key=OPENROUTER_API_KEY),
        async_client=AsyncOpenAI(base_url=OPENROUTER_BASE, api_key=OPENROUTER_API_KEY),
        extra_headers=dict(_OPENROUTER_HEADERS),
        is_byok=False,
        sdk="openai",
    )


def _get_user_credentials_row(user_id: int, *, require_enabled: bool) -> Optional[dict]:
    enabled_filter = "AND enabled = TRUE" if require_enabled else ""
    with get_session() as sess:
        row = sess.execute(
            text(
                f"""
                SELECT provider, base_url, model, api_key_ciphertext, api_key_nonce,
                       key_fingerprint, auth_method, invalidated_at, enabled, created_at, updated_at
                FROM user_llm_credentials
                WHERE user_id = :uid AND invalidated_at IS NULL
                {enabled_filter}
                """
            ),
            {"uid": user_id},
        ).mappings().first()
        return dict(row) if row else None


def get_user_credentials(user_id: int) -> Optional[dict]:
    return _get_user_credentials_row(user_id, require_enabled=True)


def user_has_byok(user_id: int | None) -> bool:
    if user_id is None:
        return False
    return get_user_credentials(user_id) is not None


def save_user_credentials(
    user_id: int,
    *,
    provider: str,
    api_key: str,
    base_url: str | None = None,
    model: str | None = None,
    auth_method: str = "manual",
) -> dict:
    provider = (provider or "").strip().lower()
    if provider not in PROVIDER_PRESETS:
        raise ValueError(f"Unsupported provider: {provider}")
    preset = PROVIDER_PRESETS[provider]
    resolved_base = (base_url or preset["base_url"] or "").rstrip("/")
    if provider == "custom" and not resolved_base:
        raise ValueError("Custom provider requires base_url")
    if not api_key.strip():
        raise ValueError("api_key required")

    enc = encrypt_api_key(api_key.strip())
    resolved_model = (model or preset["default_model"] or DEFAULT_MODEL).strip()

    auth_method = auth_method if auth_method in {"manual", "oauth"} else "manual"

    with get_session() as sess:
        sess.execute(
            text(
                """
                INSERT INTO user_llm_credentials
                    (user_id, provider, base_url, model, api_key_ciphertext,
                     api_key_nonce, key_fingerprint, auth_method, invalidated_at, enabled,
                     created_at, updated_at)
                VALUES
                    (:uid, :provider, :base_url, :model, :ct, :nonce, :fp, :auth_method, NULL, TRUE, now(), now())
                ON CONFLICT (user_id) DO UPDATE SET
                    provider = EXCLUDED.provider,
                    base_url = EXCLUDED.base_url,
                    model = EXCLUDED.model,
                    api_key_ciphertext = EXCLUDED.api_key_ciphertext,
                    api_key_nonce = EXCLUDED.api_key_nonce,
                    key_fingerprint = EXCLUDED.key_fingerprint,
                    auth_method = EXCLUDED.auth_method,
                    invalidated_at = NULL,
                    enabled = TRUE,
                    updated_at = now()
                """
            ),
            {
                "uid": user_id,
                "provider": provider,
                "base_url": resolved_base,
                "model": resolved_model,
                "ct": enc.ciphertext,
                "nonce": enc.nonce,
                "fp": enc.fingerprint,
                "auth_method": auth_method,
            },
        )
        sess.commit()

    return {
        "provider": provider,
        "base_url": resolved_base,
        "model": resolved_model,
        "key_fingerprint": enc.fingerprint,
        "auth_method": auth_method,
        "enabled": True,
    }


def delete_user_credentials(user_id: int) -> bool:
    with get_session() as sess:
        result = sess.execute(
            text("DELETE FROM user_llm_credentials WHERE user_id = :uid"),
            {"uid": user_id},
        )
        sess.commit()
        return (result.rowcount or 0) > 0


def credentials_public_view(user_id: int) -> Optional[dict]:
    row = _get_user_credentials_row(user_id, require_enabled=False)
    if not row:
        return None
    return {
        "provider": row["provider"],
        "base_url": row["base_url"],
        "model": row["model"],
        "key_fingerprint": row["key_fingerprint"],
        "auth_method": row.get("auth_method") or "manual",
        "enabled": bool(row.get("enabled", True)),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


def update_user_credentials_model(user_id: int, model: str) -> Optional[dict]:
    resolved_model = (model or "").strip()
    if not resolved_model:
        raise ValueError("model required")
    with get_session() as sess:
        result = sess.execute(
            text(
                """
                UPDATE user_llm_credentials
                SET model = :model, updated_at = now()
                WHERE user_id = :uid AND invalidated_at IS NULL
                """
            ),
            {"uid": user_id, "model": resolved_model},
        )
        sess.commit()
        if (result.rowcount or 0) <= 0:
            return None
    return credentials_public_view(user_id)


def update_user_credentials_enabled(user_id: int, enabled: bool) -> Optional[dict]:
    with get_session() as sess:
        result = sess.execute(
            text(
                """
                UPDATE user_llm_credentials
                SET enabled = :enabled, updated_at = now()
                WHERE user_id = :uid AND invalidated_at IS NULL
                """
            ),
            {"uid": user_id, "enabled": bool(enabled)},
        )
        sess.commit()
        if (result.rowcount or 0) <= 0:
            return None
    return credentials_public_view(user_id)


def mark_user_credentials_invalid(user_id: int | None) -> None:
    if user_id is None:
        return
    with get_session() as sess:
        sess.execute(
            text(
                """
                UPDATE user_llm_credentials
                SET invalidated_at = now(), updated_at = now()
                WHERE user_id = :uid AND invalidated_at IS NULL
                """
            ),
            {"uid": user_id},
        )
        sess.commit()


def resolve_runtime(user_id: int | None) -> LlmRuntime:
    if user_id is None:
        return shared_openrouter_runtime()

    row = get_user_credentials(user_id)
    if not row:
        return shared_openrouter_runtime()

    api_key = decrypt_api_key(bytes(row["api_key_ciphertext"]), bytes(row["api_key_nonce"]))
    provider = row["provider"]
    base_url = row["base_url"]
    model = row["model"] or DEFAULT_MODEL

    if provider == "anthropic":
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError("anthropic package required for Anthropic BYOK") from e
        sync_c = anthropic.Anthropic(api_key=api_key)
        async_c = anthropic.AsyncAnthropic(api_key=api_key)
        return LlmRuntime(
            provider=provider,
            model=model,
            sync_client=sync_c,
            async_client=async_c,
            extra_headers={},
            is_byok=True,
            sdk="anthropic",
        )

    headers = dict(_OPENROUTER_HEADERS) if "openrouter.ai" in base_url else {}
    return LlmRuntime(
        provider=provider,
        model=model,
        sync_client=OpenAI(base_url=base_url, api_key=api_key),
        async_client=AsyncOpenAI(base_url=base_url, api_key=api_key),
        extra_headers=headers,
        is_byok=True,
        sdk="openai",
    )


async def validate_credentials(provider: str, api_key: str, base_url: str | None, model: str | None) -> None:
    """Cheap validation call; raises on failure."""
    provider = provider.lower()
    preset = PROVIDER_PRESETS.get(provider)
    if not preset:
        raise ValueError("unsupported provider")
    resolved_base = (base_url or preset["base_url"] or "").rstrip("/")
    resolved_model = model or preset["default_model"] or DEFAULT_MODEL

    if provider == "anthropic":
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=api_key)
        await client.messages.create(
            model=resolved_model,
            max_tokens=8,
            messages=[{"role": "user", "content": "ping"}],
        )
        return

    if not resolved_base:
        raise ValueError("base_url required")
    client = AsyncOpenAI(base_url=resolved_base, api_key=api_key)
    # models.list is enough for most OpenAI-compat providers
    try:
        await client.models.list()
    except Exception:
        # Some providers disable /models — fall back to tiny completion
        await client.chat.completions.create(
            model=resolved_model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=4,
        )
