"""Shared pre-flight for chat: scope guard, device cookie, quota, agent context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Request, Response

from agentic_chatbot.agent_context import AgentContext

from . import llm_clients, quota
from .device_id import DeviceContext, attach_device_cookie, ensure_device_cookie
from .models import User
from .scope_guard import REFUSAL_MESSAGE, check_academic_scope


@dataclass
class ChatGateResult:
    allowed: bool
    refusal: str | None = None
    device: DeviceContext | None = None
    agent_ctx: AgentContext | None = None
    quota_status: quota.QuotaStatus | None = None


def gate_chat_request(
    *,
    request: Request,
    response: Response,
    message: str,
    user: Optional[User],
    chat_id: Optional[int] = None,
) -> ChatGateResult:
    device = ensure_device_cookie(request, response)

    scope = check_academic_scope(message)
    if not scope.allowed:
        return ChatGateResult(
            allowed=False,
            refusal=scope.message or REFUSAL_MESSAGE,
            device=device,
        )

    user_id = int(user.id) if user and user.id is not None else None
    has_byok = llm_clients.user_has_byok(user_id) if user_id else False
    q = quota.check_quota(
        user_id=user_id,
        device_fingerprint=device.fingerprint,
        has_byok=has_byok,
    )
    if not q.allowed:
        detail = {
            "error": "quota_exceeded",
            "message": (
                f"Token limit reached ({q.used}/{q.limit} in {q.window_hours:g}h). "
                "Add your own API key in Profile to continue, or wait for the window to reset."
            ),
            "used": q.used,
            "limit": q.limit,
            "remaining": q.remaining,
            "window_hours": q.window_hours,
            "resets_at": q.resets_at.isoformat() if q.resets_at else None,
            "byok": q.byok,
        }
        raise HTTPException(status_code=429, detail=detail)

    runtime = llm_clients.resolve_runtime(user_id)
    agent_ctx = AgentContext(
        runtime=runtime,
        user_id=user_id,
        device_fingerprint=device.fingerprint,
        chat_id=chat_id,
    )
    return ChatGateResult(
        allowed=True,
        device=device,
        agent_ctx=agent_ctx,
        quota_status=q,
    )
