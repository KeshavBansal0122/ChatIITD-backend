"""Per-request agent context: LLM runtime + usage accounting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from backend.llm_clients import LlmRuntime


@dataclass
class AgentContext:
    runtime: "LlmRuntime"
    user_id: Optional[int] = None
    device_fingerprint: Optional[str] = None
    chat_id: Optional[int] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def add_usage(self, prompt: int = 0, completion: int = 0) -> None:
        self.prompt_tokens += max(0, int(prompt or 0))
        self.completion_tokens += max(0, int(completion or 0))

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def flush_usage(self) -> None:
        from backend.quota import record_usage

        if self.prompt_tokens or self.completion_tokens:
            record_usage(
                user_id=self.user_id,
                device_fingerprint=self.device_fingerprint,
                provider=self.runtime.provider,
                model=self.runtime.model,
                prompt_tokens=self.prompt_tokens,
                completion_tokens=self.completion_tokens,
                chat_id=self.chat_id,
            )
        self.prompt_tokens = 0
        self.completion_tokens = 0


def usage_from_openai_response(response) -> tuple[int, int]:
    """Return (billable_prompt, completion). Cached prompt tokens are excluded."""
    usage = getattr(response, "usage", None)
    if not usage:
        return 0, 0
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    cached = 0
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        if isinstance(details, dict):
            cached = int(details.get("cached_tokens") or 0)
        else:
            cached = int(getattr(details, "cached_tokens", 0) or 0)
    return max(0, prompt - cached), completion


def usage_from_anthropic_response(response) -> tuple[int, int]:
    """Anthropic input_tokens already excludes cache reads; count those."""
    usage = getattr(response, "usage", None)
    if not usage:
        return 0, 0
    return int(getattr(usage, "input_tokens", 0) or 0), int(
        getattr(usage, "output_tokens", 0) or 0
    )
