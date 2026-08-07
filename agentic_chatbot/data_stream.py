"""
Minimal Vercel AI data-stream v1 encoder for assistant-ui.

Wire format consumed by `@assistant-ui/react-data-stream` / `DataStreamDecoder`.
Header: `x-vercel-ai-data-stream: v1`
"""

from __future__ import annotations

import json
from typing import Any


def _line(prefix: str, value: Any) -> str:
    return f"{prefix}:{json.dumps(value, ensure_ascii=False)}\n"


def text_delta(text: str) -> str:
    return _line("0", text)


def data(items: list[Any]) -> str:
    return _line("2", items)


def error(message: str) -> str:
    return _line("3", message)


def tool_call_begin(tool_call_id: str, tool_name: str) -> str:
    return _line("b", {"toolCallId": tool_call_id, "toolName": tool_name})


def tool_call_args_delta(tool_call_id: str, args_text_delta: str) -> str:
    return _line(
        "c",
        {"toolCallId": tool_call_id, "argsTextDelta": args_text_delta},
    )


def tool_call_result(tool_call_id: str, result: Any, *, is_error: bool = False) -> str:
    payload: dict[str, Any] = {"toolCallId": tool_call_id, "result": result}
    if is_error:
        payload["isError"] = True
    return _line("a", payload)


def finish_message(
    finish_reason: str = "stop",
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> str:
    return _line(
        "d",
        {
            "finishReason": finish_reason,
            "usage": {
                "inputTokens": int(input_tokens or 0),
                "outputTokens": int(output_tokens or 0),
            },
        },
    )


def finish_step(
    finish_reason: str = "stop",
    *,
    is_continued: bool = False,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> str:
    return _line(
        "e",
        {
            "finishReason": finish_reason,
            "usage": {
                "inputTokens": int(input_tokens or 0),
                "outputTokens": int(output_tokens or 0),
            },
            "isContinued": is_continued,
        },
    )


DATA_STREAM_HEADERS = {
    "Content-Type": "text/plain; charset=utf-8",
    "x-vercel-ai-data-stream": "v1",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
