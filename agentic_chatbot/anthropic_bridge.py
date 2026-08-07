"""Anthropic Messages API adapter for the ReAct tool loop (BYOK)."""

from __future__ import annotations

import json
from typing import Any

from .tools import TOOLS, execute_tool


def openai_tools_to_anthropic() -> list[dict]:
    out = []
    for t in TOOLS:
        fn = t.get("function") or {}
        out.append(
            {
                "name": fn.get("name"),
                "description": fn.get("description") or "",
                "input_schema": fn.get("parameters")
                or {"type": "object", "properties": {}},
            }
        )
    return out


def openai_messages_to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    """Split system text and convert chat messages to Anthropic format."""
    system_parts: list[str] = []
    out: list[dict] = []

    for msg in messages:
        role = msg.get("role")
        if role == "system":
            content = msg.get("content") or ""
            if content:
                system_parts.append(content)
            continue

        if role == "user":
            out.append({"role": "user", "content": msg.get("content") or ""})
            continue

        if role == "assistant":
            content_blocks: list[dict] = []
            text = msg.get("content")
            if text:
                content_blocks.append({"type": "text", "text": text})
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id") or "tool",
                        "name": fn.get("name") or "",
                        "input": args,
                    }
                )
            if content_blocks:
                out.append({"role": "assistant", "content": content_blocks})
            continue

        if role == "tool":
            # Anthropic expects tool_result in a user message
            block = {
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id"),
                "content": msg.get("content") or "",
            }
            if out and out[-1].get("role") == "user" and isinstance(out[-1].get("content"), list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
            continue

    return "\n\n".join(system_parts), out


def anthropic_response_to_openai_assistant(response) -> dict:
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    for block in response.content or []:
        btype = getattr(block, "type", None)
        if btype == "text":
            text_parts.append(getattr(block, "text", "") or "")
        elif btype == "tool_use":
            tool_calls.append(
                {
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input or {}),
                    },
                }
            )
    msg: dict[str, Any] = {
        "role": "assistant",
        "content": "\n".join(text_parts) if text_parts else None,
    }
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg
