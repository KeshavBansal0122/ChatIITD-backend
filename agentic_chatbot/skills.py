"""Progressive-disclosure skills for the IIT Delhi chatbot.

Skill files live at ``backend/agentic_chatbot/skills/<name>/SKILL.md`` with
small YAML-style frontmatter:

---
name: skill-name
description: When to load this skill.
---
Full skill body...
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_SKILLS_ROOT = Path(__file__).resolve().parent / "skills"


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path


def _parse_skill(path: Path) -> Skill | None:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        return None
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return None

    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"').strip("'")

    name = meta.get("name") or path.parent.name
    description = meta.get("description")
    if not name or not description:
        return None
    return Skill(name=name, description=description, path=path)


def discover_skills() -> list[Skill]:
    """Discover available skills once from the local skills directory."""
    if not _SKILLS_ROOT.exists():
        return []
    skills: list[Skill] = []
    for path in sorted(_SKILLS_ROOT.glob("*/SKILL.md")):
        skill = _parse_skill(path)
        if skill:
            skills.append(skill)
    return skills


_SKILLS = {skill.name: skill for skill in discover_skills()}


def build_skills_index() -> str:
    """Render the small prompt-resident skill index."""
    if not _SKILLS:
        return "- No dynamic skills are available."
    return "\n".join(
        f"- `{skill.name}`: {skill.description}"
        for skill in sorted(_SKILLS.values(), key=lambda s: s.name)
    )


def load_skill(name: str) -> str:
    """Return the full body of a named skill, excluding frontmatter."""
    key = (name or "").strip()
    skill = _SKILLS.get(key)
    if not skill:
        available = ", ".join(sorted(_SKILLS)) or "none"
        return f"Skill '{name}' not found. Available skills: {available}."

    raw = skill.path.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    body = parts[2].strip() if len(parts) >= 3 else raw.strip()
    return f"# Skill: {skill.name}\n\n{body}"
