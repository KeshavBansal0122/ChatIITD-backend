"""
Password-gated admin portal API.

Auth is independent of OIDC user roles: set ADMIN_PASSWORD in .env, then
POST /portal/login to receive a short-lived portal JWT.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlmodel import text

from . import auth, models
from .logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/portal", tags=["Admin Portal"])
_bearer = HTTPBearer(auto_error=False)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
PORTAL_TOKEN_HOURS = int(os.environ.get("ADMIN_PORTAL_TOKEN_HOURS", "12"))
PORTAL_TYP = "portal"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PortalLoginRequest(BaseModel):
    password: str = Field(..., min_length=1)


class PortalLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_hours: int


class ToolRunRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    # Optional user context for generation-gated tools
    curriculum_generation: Optional[str] = Field(
        default=None, description="legacy | 2025"
    )
    year_of_joining: Optional[int] = None


class RagTestRequest(BaseModel):
    query: str = Field(..., min_length=1)
    generation: str = Field(..., description="legacy | 2025")
    doc_types: Optional[list[str]] = None
    limit: int = Field(default=8, ge=1, le=30)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _password_configured() -> bool:
    return bool(ADMIN_PASSWORD and ADMIN_PASSWORD.strip())


def _password_ok(provided: str) -> bool:
    if not _password_configured():
        return False
    expected = ADMIN_PASSWORD.encode("utf-8")
    got = provided.encode("utf-8")
    # compare_digest requires equal length; hash first so lengths always match
    return hmac.compare_digest(
        hashlib.sha256(got).digest(),
        hashlib.sha256(expected).digest(),
    )


def create_portal_token() -> str:
    expire = datetime.utcnow() + timedelta(hours=PORTAL_TOKEN_HOURS)
    payload = {
        "sub": "portal_admin",
        "typ": PORTAL_TYP,
        "exp": expire,
        "iat": datetime.utcnow(),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, auth.JWT_SECRET, algorithm=auth.JWT_ALGORITHM)


def require_portal(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    if not _password_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_PASSWORD is not set on the server",
        )
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Portal authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(
            credentials.credentials,
            auth.JWT_SECRET,
            algorithms=[auth.JWT_ALGORITHM],
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired portal token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if payload.get("typ") != PORTAL_TYP:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not a portal token",
        )
    return payload


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/login", response_model=PortalLoginResponse)
def portal_login(body: PortalLoginRequest):
    if not _password_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_PASSWORD is not set on the server",
        )
    if not _password_ok(body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password",
        )
    return PortalLoginResponse(
        access_token=create_portal_token(),
        expires_in_hours=PORTAL_TOKEN_HOURS,
    )


@router.get("/me")
def portal_me(_: dict = Depends(require_portal)):
    return {"ok": True, "role": "portal_admin"}


@router.get("/stats")
def portal_stats(_: dict = Depends(require_portal)):
    """Usage + corpus stats for the admin dashboard."""
    now = datetime.utcnow()
    windows = {
        "1d": now - timedelta(days=1),
        "7d": now - timedelta(days=7),
        "30d": now - timedelta(days=30),
    }
    out: dict[str, Any] = {"generated_at": now.isoformat() + "Z"}

    try:
        with models.get_session() as sess:
            out["users_total"] = sess.execute(text('SELECT count(*) FROM "user"')).one()[0]
            out["chats_total"] = sess.execute(text("SELECT count(*) FROM chat")).one()[0]
            out["messages_total"] = sess.execute(text("SELECT count(*) FROM message")).one()[0]

            active = {}
            messages_by_window = {}
            for label, cutoff in windows.items():
                active[label] = sess.execute(
                    text(
                        """
                        SELECT count(DISTINCT c.user_id)
                        FROM message m
                        JOIN chat c ON c.id = m.chat_id
                        WHERE m.created_at >= :cutoff
                        """
                    ),
                    {"cutoff": cutoff},
                ).one()[0]
                messages_by_window[label] = sess.execute(
                    text("SELECT count(*) FROM message WHERE created_at >= :cutoff"),
                    {"cutoff": cutoff},
                ).one()[0]
            out["active_users"] = active
            out["messages_by_window"] = messages_by_window

            out["new_chats"] = {
                label: sess.execute(
                    text("SELECT count(*) FROM chat WHERE created_at >= :cutoff"),
                    {"cutoff": cutoff},
                ).one()[0]
                for label, cutoff in windows.items()
            }

            out["courses_by_generation"] = {
                str(r[0] or "unknown"): r[1]
                for r in sess.execute(
                    text("SELECT generation, count(*) FROM course GROUP BY generation")
                ).all()
            }
            out["courses_total"] = sess.execute(text("SELECT count(*) FROM course")).one()[0]
            out["programmes_by_generation"] = {
                str(r[0] or "unknown"): r[1]
                for r in sess.execute(
                    text("SELECT generation, count(*) FROM programme GROUP BY generation")
                ).all()
            }
            out["catalog_courses"] = sess.execute(
                text("SELECT count(*) FROM catalog_courses")
            ).one()[0]
            out["semesters"] = [
                {
                    "code": r[0],
                    "label": r[1],
                    "is_active": bool(r[2]),
                }
                for r in sess.execute(
                    text(
                        "SELECT code, label, is_active FROM semesters ORDER BY code DESC"
                    )
                ).all()
            ]

            out["recent_chats"] = [
                {
                    "id": r[0],
                    "user_id": r[1],
                    "title": r[2],
                    "created_at": r[3].isoformat() if r[3] else None,
                    "user_email": r[4],
                    "kerberos": r[5],
                }
                for r in sess.execute(
                    text(
                        """
                        SELECT c.id, c.user_id, c.title, c.created_at, u.email, u.kerberos
                        FROM chat c
                        LEFT JOIN "user" u ON u.id = c.user_id
                        ORDER BY c.created_at DESC
                        LIMIT 15
                        """
                    )
                ).all()
            ]
    except Exception as e:
        logger.exception("portal stats DB failed")
        out["db_error"] = str(e)

    # Knowledge / Qdrant
    try:
        from backend.knowledge_service import (
            KNOWLEDGE_COLLECTION,
            _get_client,
            ensure_knowledge_collection,
        )

        ensure_knowledge_collection()
        info = _get_client().get_collection(KNOWLEDGE_COLLECTION)
        out["knowledge"] = {
            "collection": KNOWLEDGE_COLLECTION,
            "points_count": getattr(info, "points_count", None)
            or getattr(getattr(info, "result", None), "points_count", None),
            "status": str(getattr(info, "status", "")),
        }
        # Sample generation / doc_type facets via scroll
        client = _get_client()
        records, _ = client.scroll(
            collection_name=KNOWLEDGE_COLLECTION,
            limit=500,
            with_payload=True,
            with_vectors=False,
        )
        gen_counts: dict[str, int] = {}
        type_counts: dict[str, int] = {}
        for r in records:
            p = r.payload or {}
            g = str(p.get("generation") or (p.get("metadata") or {}).get("generation") or "unknown")
            d = str(p.get("doc_type") or (p.get("metadata") or {}).get("doc_type") or "unknown")
            gen_counts[g] = gen_counts.get(g, 0) + 1
            type_counts[d] = type_counts.get(d, 0) + 1
        out["knowledge"]["sample_size"] = len(records)
        out["knowledge"]["generation_sample"] = gen_counts
        out["knowledge"]["doc_type_sample"] = type_counts
    except Exception as e:
        logger.warning("portal knowledge stats failed: %s", e)
        out["knowledge"] = {"error": str(e)}

    return out


@router.get("/tools")
def list_tools(_: dict = Depends(require_portal)):
    from agentic_chatbot.tools import TOOLS, TOOL_MAPPING

    tools = []
    for t in TOOLS:
        fn = t.get("function") or {}
        name = fn.get("name")
        tools.append(
            {
                "name": name,
                "description": fn.get("description") or "",
                "parameters": fn.get("parameters") or {},
                "runnable": name in TOOL_MAPPING,
            }
        )
    return {"tools": tools}


@router.post("/tools/run")
def run_tool(body: ToolRunRequest, _: dict = Depends(require_portal)):
    from agentic_chatbot.tools import (
        TOOL_MAPPING,
        execute_tool,
        set_tool_user_context,
    )

    if body.tool_name not in TOOL_MAPPING:
        raise HTTPException(status_code=404, detail=f"Unknown tool '{body.tool_name}'")

    ctx: dict[str, Any] = {}
    if body.curriculum_generation:
        ctx["curriculum_generation"] = body.curriculum_generation
    if body.year_of_joining is not None:
        ctx["year_of_joining"] = body.year_of_joining
    set_tool_user_context(ctx or None)

    started = datetime.utcnow()
    try:
        result = execute_tool(body.tool_name, body.arguments or {})
    except Exception as e:
        logger.exception("portal tool run failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        set_tool_user_context(None)

    elapsed_ms = int((datetime.utcnow() - started).total_seconds() * 1000)

    # Try to parse JSON results for nicer UI
    parsed: Any = None
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            parsed = None

    return {
        "tool_name": body.tool_name,
        "arguments": body.arguments,
        "elapsed_ms": elapsed_ms,
        "result": result,
        "result_json": parsed,
    }


@router.post("/rag/test")
def rag_test(body: RagTestRequest, _: dict = Depends(require_portal)):
    """Run hybrid_search and return structured chunks for inspection."""
    if body.generation not in ("legacy", "2025"):
        raise HTTPException(
            status_code=400,
            detail="generation must be 'legacy' or '2025'",
        )
    try:
        from backend.knowledge_service import format_hit_citation, hybrid_search
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Knowledge service unavailable: {e}") from e

    started = datetime.utcnow()
    try:
        hits = hybrid_search(
            body.query,
            generation=body.generation,
            doc_types=body.doc_types,
            limit=body.limit,
        )
    except Exception as e:
        logger.exception("portal rag test failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    elapsed_ms = int((datetime.utcnow() - started).total_seconds() * 1000)

    chunks = []
    for i, hit in enumerate(hits, start=1):
        meta = hit.get("metadata") or {}
        chunks.append(
            {
                "rank": i,
                "id": hit.get("id"),
                "score": hit.get("score"),
                "generation": hit.get("generation") or meta.get("generation"),
                "doc_type": hit.get("doc_type") or meta.get("doc_type"),
                "source_name": meta.get("source_name") or meta.get("source_file"),
                "source_url": hit.get("source_url") or meta.get("source_url"),
                "page_start": meta.get("page_start") or meta.get("page"),
                "page_end": meta.get("page_end"),
                "section_title": meta.get("section_title"),
                "section_path": meta.get("section_path"),
                "course_code": meta.get("course_code"),
                "programme_code": meta.get("programme_code"),
                "content": hit.get("content") or "",
                "citation": format_hit_citation(hit),
                "metadata": meta,
            }
        )

    return {
        "query": body.query,
        "generation": body.generation,
        "doc_types": body.doc_types,
        "limit": body.limit,
        "elapsed_ms": elapsed_ms,
        "hit_count": len(chunks),
        "chunks": chunks,
    }
