"""Curriculum generation helpers: legacy (entry ≤2024) vs 2025 (entry ≥2025)."""

from __future__ import annotations

from typing import Optional

GENERATION_LEGACY = "legacy"
GENERATION_2025 = "2025"


def generation_from_entry_year(year: Optional[int]) -> Optional[str]:
    """Map year of joining to curriculum generation. None if unknown."""
    if year is None:
        return None
    try:
        y = int(year)
    except (TypeError, ValueError):
        return None
    return GENERATION_LEGACY if y <= 2024 else GENERATION_2025


def resolve_generation(
    explicit: Optional[str] = None,
    year_of_joining: Optional[int] = None,
    default: Optional[str] = None,
) -> Optional[str]:
    """Prefer explicit tool arg, then entry year, then optional default."""
    if explicit in (GENERATION_LEGACY, GENERATION_2025):
        return explicit
    if explicit:
        e = str(explicit).strip().lower()
        if e in ("legacy", "old", "2024", "pre-2025", "pre2025"):
            return GENERATION_LEGACY
        if e in ("2025", "new", "2026", "current"):
            return GENERATION_2025
    derived = generation_from_entry_year(year_of_joining)
    if derived:
        return derived
    return default
