"""
Server-side academic scope guard.

Ambiguous / short lookups pass through (tools decide).
Clear off-mission requests are denied before the LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

REFUSAL_MESSAGE = (
    "I only help with IIT Delhi academics (courses, rules, instructors, planning). "
    "Ask about a course, professor, or policy."
)

# Strong off-topic signals (coding / homework / general chat)
_DENY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.I)
    for p in [
        r"\bleetcode\b",
        r"\bhacker\s*rank\b",
        r"\bcodeforces\b",
        r"\batcoder\b",
        r"\bwrite\s+(a|me\s+a|an)\s+(python|java|c\+\+|javascript|typescript|go|rust)\b",
        r"\bimplement\s+(a|an|the)\s+\w+\s+(function|class|algorithm|sort|tree|graph)\b",
        r"\bsolve\s+(this|the)\s+(coding|programming|algorithm|leetcode)\b",
        r"\bfix\s+(this|my|the)\s+(bug|code|error|stack\s*trace)\b",
        r"\bdebug\s+(this|my|the)\s+code\b",
        r"```(?:python|java|cpp|c\+\+|javascript|typescript|go|rust)",
        r"\btime\s+complexity\b.*\bspace\s+complexity\b",
        r"\bwrite\s+(me\s+)?(an?\s+)?essay\b",
        r"\bwrite\s+(me\s+)?(a\s+)?poem\b",
        r"\bact\s+as\s+(a\s+)?(girlfriend|boyfriend|therapist|lawyer|doctor)\b",
        r"\bignore\s+(all\s+)?(previous|prior)\s+instructions\b",
        r"\byou\s+are\s+now\s+dan\b",
        r"\bgenerate\s+nsfw\b",
    ]
]

# Soft allow: academic / IITD vocabulary — reduces false denies
_ALLOW_HINTS = re.compile(
    r"\b("
    r"iitd|iit\s*delhi|course|courses|slot|credits?|prereq|prerequisite|"
    r"semester|programme|program|minor|major|hostel|kerberos|"
    r"registration|attendance|grading|cgpa|sgpa|audit|withdraw|"
    r"instructor|professor|faculty|offering|catalog|timetable|"
    r"col\d{3}|mtl\d{3}|ell\d{3}|hul\d{3}|aml\d{3}|cvl\d{3}|"
    r"who\s+teaches|search\s+\w+|offered|dept|department"
    r")\b",
    re.I,
)

_COURSE_CODE = re.compile(r"\b[A-Za-z]{2,3}[LPDNVS]?\d{3,4}\b")


@dataclass
class ScopeDecision:
    allowed: bool
    reason: str = ""
    message: str = ""


def check_academic_scope(user_message: str) -> ScopeDecision:
    text = (user_message or "").strip()
    if not text:
        return ScopeDecision(False, "empty", REFUSAL_MESSAGE)

    # Short / ambiguous name-like lookups: allow (tools handle)
    words = text.split()
    if len(words) <= 6 and not any(p.search(text) for p in _DENY_PATTERNS):
        return ScopeDecision(True, "short_or_ambiguous")

    if _COURSE_CODE.search(text) or _ALLOW_HINTS.search(text):
        # Academic signal present — allow even if mixed with other chatter
        return ScopeDecision(True, "academic_signal")

    for pat in _DENY_PATTERNS:
        if pat.search(text):
            return ScopeDecision(False, f"deny:{pat.pattern[:40]}", REFUSAL_MESSAGE)

    # Default: allow; model + tools still constrained by system prompt
    return ScopeDecision(True, "default_allow")
