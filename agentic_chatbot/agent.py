"""
IIT Delhi Academic Chatbot Agent using OpenRouter.

ReAct-style agent with tool calling, exposed in three flavors:
- invoke_memory_agent: synchronous, returns full response
- stream_memory_agent: async, yields response tokens
- stream_memory_agent_with_status: async, yields structured events (tokens + tool-call status)
"""

import os
import re
import json
from typing import AsyncGenerator
from pathlib import Path
from openai import (
    OpenAI, AsyncOpenAI,
    PermissionDeniedError, AuthenticationError, RateLimitError,
    APITimeoutError, BadRequestError, APIStatusError,
)
from dotenv import load_dotenv

from .tools import TOOLS, execute_tool

try:
    from backend.logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


load_dotenv('../.env')
load_dotenv('.env')


# =====================
# Configuration
# =====================

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
MODEL = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-haiku-4.5")
MAX_TOOL_ITERATIONS = 30
FINAL_RESPONSE_MAX_TOKENS = 800

_OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://chatiitd.devclub.in",
    "X-OpenRouter-Title": "ChatIITD Academic Assistant",
}

logger.info(f"OpenRouter API Key configured: {'Yes' if OPENROUTER_API_KEY else 'NO - MISSING!'}")
logger.info(f"Using model: {MODEL}")

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
async_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)


# =====================
# Error Classification
# =====================

_ERROR_MAP = {
    400: ("bad_request", "The request was invalid. Please try again."),
    401: ("unauthorized", "API authentication failed. Please contact the administrator."),
    402: ("insufficient_credits", "The AI service has run out of credits. Please contact the administrator."),
    403: ("forbidden", "The AI service key limit has been exceeded. Please contact the administrator."),
    408: ("timeout", "The AI service timed out. Please try again."),
    429: ("rate_limited", "Too many requests to the AI service. Please wait a moment and try again."),
    502: ("model_unavailable", "The AI model is currently unavailable. Please try again later."),
    503: ("service_unavailable", "The AI service is unavailable. Please try again later."),
}

_EXC_FALLBACKS = (
    (AuthenticationError, "unauthorized", "API authentication failed. Please contact the administrator."),
    (PermissionDeniedError, "forbidden", "The AI service key limit has been exceeded. Please contact the administrator."),
    (RateLimitError, "rate_limited", "Too many requests to the AI service. Please wait a moment and try again."),
    (APITimeoutError, "timeout", "The AI service timed out. Please try again."),
    (BadRequestError, "bad_request", "The request was invalid. Please try again."),
)


def classify_openrouter_error(e: Exception) -> dict:
    """Classify an OpenRouter exception into {type, message, error_code} for WebSocket events."""
    status_code = e.status_code if isinstance(e, APIStatusError) else None
    if status_code is None and isinstance(getattr(e, "body", None), dict):
        status_code = e.body.get("error", {}).get("code")

    if status_code in _ERROR_MAP:
        code, msg = _ERROR_MAP[status_code]
    else:
        code, msg = "api_error", "An unexpected error occurred with the AI service. Please try again."
        for exc_type, ec, em in _EXC_FALLBACKS:
            if isinstance(e, exc_type):
                code, msg = ec, em
                break

    return {"type": "error", "message": msg, "error_code": code}


# =====================
# System Prompt + Per-turn Helpers
# =====================

_AGENT_DIR = Path(__file__).resolve().parent
with open(_AGENT_DIR / 'system_prompt.txt', 'r') as f:
    BASE_SYSTEM_PROMPT = f.read()

_COURSE_CODE_RE = re.compile(r"\b[A-Z]{2}[LPDNVS]\d{3}\b")
_DEPTH_KEYWORDS = ("full plan", "comprehensive", "all courses", "list all", "everything", "detailed", "step by step")

_USER_CONTEXT_FIELDS = [
    ("name", "Name"),
    ("email", "Email"),
    ("kerberos", "Kerberos ID"),
    ("programme_code", "Programme Code"),
    ("programme_name", "Programme"),
    ("year_of_joining", "Year of Joining"),
    ("hostel", "Hostel"),
]


def build_system_message(model: str = MODEL) -> dict:
    """
    Static base system prompt. For Anthropic-routed models, wraps content in the
    structured-array form with cache_control:ephemeral so the system + tool schemas
    prefix is cached across requests. Other providers get plain string content.
    """
    if model.startswith("anthropic/"):
        return {
            "role": "system",
            "content": [{
                "type": "text",
                "text": BASE_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
        }
    return {"role": "system", "content": BASE_SYSTEM_PROMPT}


def build_user_context_message(user_context: dict | None) -> dict | None:
    """Per-user context as a separate user-role message (kept out of the cached prefix)."""
    if not user_context:
        return None

    parts = [f"{label}: {user_context[key]}" for key, label in _USER_CONTEXT_FIELDS if user_context.get(key)]
    if user_context.get("courses_done"):
        parts.append(f"Courses Done: {json.dumps(user_context['courses_done'])}")

    if not parts:
        return None

    body = "User profile (for the assistant's reference, do not recap unless asked):\n" + "\n".join(f"- {p}" for p in parts)
    return {"role": "user", "content": body}


def maybe_clarify_hint(user_message: str) -> dict | None:
    """
    Inject an ephemeral system hint when the message is brief and context-poor,
    steering the model toward clarifying questions over a comprehensive answer.
    """
    if not user_message:
        return None
    text = user_message.strip()
    if len(text.split()) >= 15:
        return None
    if _COURSE_CODE_RE.search(text.upper()):
        return None
    lower = text.lower()
    if any(kw in lower for kw in _DEPTH_KEYWORDS):
        return None
    return {
        "role": "system",
        "content": (
            "The user's message is brief and likely under-specified. "
            "Prefer asking 1-2 focused clarifying questions over producing a comprehensive answer. "
            "Keep the reply short. Do not enumerate every related course, rule, or semester plan."
        ),
    }


def _build_initial_messages(
    user_message: str,
    session_id: str | None,
    user_context: dict | None,
) -> list[dict]:
    """Assemble the prompt prefix and persist the user message."""
    messages: list[dict] = [build_system_message(MODEL)]

    if session_id:
        messages.extend(get_chat_history(session_id))

    ctx_msg = build_user_context_message(user_context)
    if ctx_msg:
        messages.append(ctx_msg)

    hint = maybe_clarify_hint(user_message)
    if hint:
        messages.append(hint)

    user_msg = {"role": "user", "content": user_message}
    messages.append(user_msg)
    if session_id:
        add_message_to_history(session_id, user_msg)

    return messages


# =====================
# Chat History (central database)
# =====================

def get_chat_history(session_id: str) -> list[dict]:
    from backend.models import MessageHistory, get_session
    from sqlmodel import select

    messages = []
    with get_session() as session:
        rows = session.exec(
            select(MessageHistory).where(MessageHistory.session_id == session_id).order_by(MessageHistory.created_at)
        ).all()

        for row in rows:
            message = {"role": row.role}
            if row.content is not None:
                message["content"] = row.content
            if row.tool_calls:
                message["tool_calls"] = json.loads(row.tool_calls)
                if row.role == "assistant" and not row.content:
                    message["content"] = None
            if row.tool_call_id:
                message["tool_call_id"] = row.tool_call_id
            if row.name:
                message["name"] = row.name
            messages.append(message)

    return messages


def _serialize_tool_calls(tool_calls) -> list[dict]:
    """Normalize a list of tool_call objects (SDK or dict) to plain dicts for storage."""
    out = []
    for tc in tool_calls:
        if isinstance(tc, dict):
            out.append(tc)
        elif hasattr(tc, "model_dump"):
            out.append(tc.model_dump())
        else:
            out.append({
                "id": tc.id,
                "type": tc.type,
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            })
    return out


def add_message_to_history(session_id: str, message: dict):
    from backend.models import MessageHistory, get_session

    tool_calls_json = None
    if "tool_calls" in message:
        tool_calls_json = json.dumps(_serialize_tool_calls(message["tool_calls"]))

    with get_session() as session:
        session.add(MessageHistory(
            session_id=session_id,
            role=message.get("role"),
            content=message.get("content"),
            tool_calls=tool_calls_json,
            tool_call_id=message.get("tool_call_id"),
            name=message.get("name"),
        ))
        session.commit()


# =====================
# Agent Core
# =====================

def _truncate(s: str, n: int = 200) -> str:
    return s if len(s) <= n else s[:n - 3] + "..."


def process_tool_calls(tool_calls) -> list[dict]:
    """Execute a list of SDK tool_call objects and return the resulting tool messages."""
    results = []
    for tc in tool_calls:
        name = tc.function.name
        try:
            args = json.loads(tc.function.arguments)
        except json.JSONDecodeError:
            args = {}
        logger.info(f"[tool] {name}({args})")
        result = execute_tool(name, args)
        logger.info(f"[tool result] {name}: {_truncate(result)}")
        results.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    return results


def invoke_memory_agent(
    input_dict: dict,
    session_id: str | None = None,
    user_context: dict | None = None,
) -> dict:
    """Synchronous invocation. Returns {'output': str}."""
    user_message = input_dict.get("input", "")
    logger.info(f"[invoke] session={session_id} msg={_truncate(user_message, 100)}")

    messages = _build_initial_messages(user_message, session_id, user_context)

    for iteration in range(1, MAX_TOOL_ITERATIONS + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                extra_headers=_OPENROUTER_HEADERS,
            )
        except Exception as e:
            logger.error(f"[invoke] API call failed: {e}", exc_info=True)
            return {"output": f"Sorry, I encountered an error while processing your request: {e}"}

        if not response.choices:
            return {"output": "Sorry, I received an empty response from the AI service."}

        msg = response.choices[0].message
        tool_calls = msg.tool_calls
        logger.info(f"[invoke] iter={iteration} finish={response.choices[0].finish_reason} tool_calls={len(tool_calls) if tool_calls else 0}")

        assistant_msg = {"role": "assistant", "content": msg.content}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        if not tool_calls:
            if session_id:
                add_message_to_history(session_id, assistant_msg)
            return {"output": msg.content or ""}

        tool_messages = process_tool_calls(tool_calls)
        messages.extend(tool_messages)

        if session_id:
            add_message_to_history(session_id, assistant_msg)
            for tm in tool_messages:
                add_message_to_history(session_id, tm)

    logger.warning(f"[invoke] hit MAX_TOOL_ITERATIONS={MAX_TOOL_ITERATIONS}")
    return {"output": "I apologize, but I couldn't complete the request within the allowed number of steps."}


def format_tool_status(tool_name: str, arguments: dict) -> str:
    """Format a tool call for status display, truncating long arg values."""
    if not arguments:
        return tool_name
    items = []
    for k, v in arguments.items():
        v_str = str(v)
        if len(v_str) > 50:
            v_str = v_str[:47] + "..."
        items.append(f"{k}={v_str}")
    args_str = ", ".join(items)
    if len(args_str) > 100:
        return tool_name
    return f"{tool_name}({args_str})"


async def stream_memory_agent_with_status(
    input_dict: dict,
    session_id: str | None = None,
    user_context: dict | None = None,
    cancel_event: "asyncio.Event | None" = None,
) -> AsyncGenerator[dict, None]:
    """
    Async streaming with structured events:
      {type: 'status', status: 'thinking' | 'tool_call', tool?: str}
      {type: 'token', content: str}
      {type: 'done'}
      {type: 'error', message: str, error_code: str}

    One streaming call per iteration: content tokens flow immediately,
    tool_calls accumulate from deltas and dispatch at stream end.
    """
    user_message = input_dict.get("input", "")
    logger.info(f"[stream] session={session_id} msg={_truncate(user_message, 100)}")

    messages = _build_initial_messages(user_message, session_id, user_context)

    def _cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    for iteration in range(1, MAX_TOOL_ITERATIONS + 1):
        if _cancelled():
            yield {"type": "error", "message": "Generation stopped by user", "error_code": "cancelled"}
            return

        yield {"type": "status", "status": "thinking"}

        try:
            stream = await async_client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                stream=True,
                max_tokens=FINAL_RESPONSE_MAX_TOKENS,
                extra_headers=_OPENROUTER_HEADERS,
            )
        except Exception as e:
            logger.error(f"[stream] API call failed: {e}", exc_info=True)
            yield classify_openrouter_error(e)
            return

        content_buf = ""
        tool_calls_acc: dict[int, dict] = {}
        finish_reason = None

        try:
            async for chunk in stream:
                if _cancelled():
                    if session_id and content_buf:
                        add_message_to_history(session_id, {
                            "role": "assistant",
                            "content": content_buf + "\n\n[Response stopped by user]",
                        })
                    yield {"type": "error", "message": "Generation stopped by user", "error_code": "cancelled"}
                    return

                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

                if getattr(delta, "content", None):
                    content_buf += delta.content
                    yield {"type": "token", "content": delta.content}

                if getattr(delta, "tool_calls", None):
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index if tc_delta.index is not None else 0
                        slot = tool_calls_acc.setdefault(idx, {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        })
                        if tc_delta.id:
                            slot["id"] = tc_delta.id
                        fn = getattr(tc_delta, "function", None)
                        if fn is not None:
                            if fn.name:
                                slot["function"]["name"] += fn.name
                            if fn.arguments:
                                slot["function"]["arguments"] += fn.arguments

                if choice.finish_reason:
                    finish_reason = choice.finish_reason
        except Exception as e:
            logger.error(f"[stream] streaming failed: {e}", exc_info=True)
            yield classify_openrouter_error(e)
            return

        logger.info(f"[stream] iter={iteration} finish={finish_reason} content={len(content_buf)} tool_calls={len(tool_calls_acc)}")

        if tool_calls_acc:
            tool_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
            assistant_msg = {
                "role": "assistant",
                "content": content_buf or None,
                "tool_calls": tool_calls,
            }
            messages.append(assistant_msg)

            tool_messages = []
            for tc in tool_calls:
                if _cancelled():
                    yield {"type": "error", "message": "Generation stopped by user", "error_code": "cancelled"}
                    return

                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}

                yield {"type": "status", "status": "tool_call", "tool": format_tool_status(name, args)}
                logger.info(f"[tool] {name}({args})")

                result = execute_tool(name, args)
                logger.info(f"[tool result] {name}: {_truncate(result)}")

                tool_messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})

            messages.extend(tool_messages)
            if session_id:
                add_message_to_history(session_id, assistant_msg)
                for tm in tool_messages:
                    add_message_to_history(session_id, tm)

            continue

        # Final content path
        if session_id and content_buf:
            add_message_to_history(session_id, {"role": "assistant", "content": content_buf})

        if not content_buf:
            yield {"type": "token", "content": "I apologize, but I was unable to generate a response. Please try again."}

        yield {"type": "done"}
        return

    logger.warning(f"[stream] hit MAX_TOOL_ITERATIONS={MAX_TOOL_ITERATIONS}")
    yield {"type": "error", "message": "Maximum processing steps reached", "error_code": "max_iterations"}


async def stream_memory_agent(
    input_dict: dict,
    session_id: str | None = None,
    user_context: dict | None = None,
) -> AsyncGenerator[str, None]:
    """Token-only adapter over stream_memory_agent_with_status."""
    async for event in stream_memory_agent_with_status(input_dict, session_id, user_context):
        if event["type"] == "token":
            yield event["content"]
        elif event["type"] == "error":
            yield event["message"]


def generate_chat_title(user_message: str) -> str:
    """Generate a short (3-6 word) chat title from the first user message."""
    prompt = (
        "Generate a very short title (3-6 words max) for a chat that starts with this message. "
        "The title should summarize the main topic. Do not use quotes or special characters. "
        "Only respond with the title, nothing else.\n\n"
        f"User message: {user_message}\n\nTitle:"
    )
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            extra_headers=_OPENROUTER_HEADERS,
        )
    except Exception as e:
        logger.error(f"[title] failed: {e}", exc_info=True)
        return "New Chat"

    if not response.choices or not response.choices[0].message.content:
        return "New Chat"

    title = response.choices[0].message.content.strip()
    return title if title and len(title) <= 100 else "New Chat"


# =====================
# CLI
# =====================

def main():
    """Conversational command-line loop."""
    print(f"--- IIT Delhi Academic Chatbot Initialized (Model: {MODEL}) ---")
    print("Ask me about courses or institute rules. Type 'quit' to exit.")

    session_id = "cli_session"
    while True:
        try:
            query = input("You: ")
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break
        if query.lower() == "quit":
            break

        response = invoke_memory_agent({"input": query}, session_id=session_id)
        print(f"Assistant: {response['output']}\n" + "-" * 50 + "\n")


logger.info(f"--- IIT Delhi Academic Chatbot Module Loaded (Model: {MODEL}) ---")


if __name__ == "__main__":
    main()
