"""
Tools for the IIT Delhi Academic Chatbot.
These are plain Python functions with OpenAI-compatible tool schemas.
"""

from __future__ import annotations

import json
import re
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

import mwclient

from backend.courses_db import run_select_query, get_courses_by_codes, get_offerings_for_codes
from backend.curriculum.generation import resolve_generation

_THIS_DIR = Path(__file__).parent.resolve()
_BACKEND_DIR = _THIS_DIR.parent
_SOURCES_DIR = _BACKEND_DIR / "sources"
_JSONL_DIR = _SOURCES_DIR / "jsonl"
_PROGRAMME_DIR = _SOURCES_DIR / "programme_structures"

_user_context_var: ContextVar[Optional[dict]] = ContextVar("agent_user_context", default=None)


def set_tool_user_context(user_context: dict | None) -> None:
    _user_context_var.set(user_context)


def get_tool_user_context() -> dict:
    return _user_context_var.get() or {}


def read_jsonl(filename):
    res = []
    with open(filename, "r") as f:
        for line in f:
            res.append(json.loads(line))
    return res


_rules_path = _JSONL_DIR / "all_rules.jsonl"
rules_sections = read_jsonl(_rules_path) if _rules_path.exists() else []

programme_prompt = ""
_prompt_path = _PROGRAMME_DIR / "prompt.md"
if _prompt_path.exists():
    with open(_prompt_path, "r") as f:
        programme_prompt = f.read()


def _active_generation(explicit: str | None = None) -> str | None:
    ctx = get_tool_user_context()
    return resolve_generation(
        explicit=explicit,
        year_of_joining=ctx.get("year_of_joining") or ctx.get("curriculum_entry_year"),
        default=ctx.get("curriculum_generation"),
    )


# =====================
# TOOL IMPLEMENTATIONS
# =====================

def get_course_data(course_codes: list[str]) -> str:
    """
    Fetches information about specific courses offered at IIT Delhi.
    """
    codes = [code.strip() for code in course_codes]
    courses_found = get_courses_by_codes(codes)
    if courses_found:
        offered = get_offerings_for_codes(codes)
        return json.dumps({
            "courses": courses_found,
            "offerings": offered,
        })
    else:
        return "Course not found."


def query_sqlite_db(query: str) -> str:
    """
    Executes SQL queries on the 'courses.sqlite' database.
    Only SELECT queries are allowed.
    """
    return run_select_query(query)


def get_programme_structure(programme_code: str, generation: str | None = None) -> str:
    """Fetches programme structure from Postgres (both generations) with JSON fallback."""
    programme_code = programme_code.upper().strip()
    gen = _active_generation(generation)

    try:
        from sqlmodel import select
        from backend.models import (
            Programme,
            ProgrammeCourse,
            ProgrammeCreditReq,
            ProgrammeOutcome,
            ProgrammeSemester,
            get_session,
        )

        with get_session() as sess:
            q = select(Programme).where(Programme.code == programme_code)
            if gen:
                q = q.where(Programme.generation == gen)
            rows = list(sess.exec(q).all())
            if not rows and gen:
                rows = list(
                    sess.exec(select(Programme).where(Programme.code == programme_code)).all()
                )
            if rows:
                payloads = []
                for prog in rows:
                    credits = list(
                        sess.exec(
                            select(ProgrammeCreditReq).where(
                                ProgrammeCreditReq.programme_code == prog.code,
                                ProgrammeCreditReq.generation == prog.generation,
                            )
                        ).all()
                    )
                    courses = list(
                        sess.exec(
                            select(ProgrammeCourse).where(
                                ProgrammeCourse.programme_code == prog.code,
                                ProgrammeCourse.generation == prog.generation,
                            )
                        ).all()
                    )
                    semesters = list(
                        sess.exec(
                            select(ProgrammeSemester).where(
                                ProgrammeSemester.programme_code == prog.code,
                                ProgrammeSemester.generation == prog.generation,
                            )
                        ).all()
                    )
                    outcomes = list(
                        sess.exec(
                            select(ProgrammeOutcome).where(
                                ProgrammeOutcome.programme_code == prog.code,
                                ProgrammeOutcome.generation == prog.generation,
                            )
                        ).all()
                    )
                    by_cat: dict[str, list[str]] = {}
                    for c in courses:
                        by_cat.setdefault(c.category, []).append(c.course_code)
                    payloads.append(
                        {
                            "code": prog.code,
                            "generation": prog.generation,
                            "name": prog.name,
                            "degree_type": prog.degree_type,
                            "dual": prog.dual,
                            "source_url": prog.source_url,
                            "credits": {
                                c.category: c.credits_or_units
                                for c in credits
                                if c.kind == "graded"
                            },
                            "ngu": {
                                c.category: c.credits_or_units
                                for c in credits
                                if c.kind == "ngu"
                            },
                            "courses": by_cat,
                            "recommended": [
                                s.entries
                                for s in sorted(semesters, key=lambda x: x.semester)
                            ],
                            "outcomes": [
                                {"id": o.outcome_id, "text": o.text} for o in outcomes
                            ],
                        }
                    )
                body = json.dumps(payloads if len(payloads) > 1 else payloads[0], indent=2)
                return programme_prompt + "\n\n" + body
    except Exception as e:
        print(f"[get_programme_structure] DB lookup failed: {e}")

    programme_file = _PROGRAMME_DIR / f"{programme_code}.json"
    try:
        with open(programme_file, "r") as f:
            programme_data = f.read()
        return programme_prompt + "\n\n" + programme_data
    except FileNotFoundError:
        return "Programme code not found."


def get_rules_section(section_name: str) -> str:
    sections = [
        sec
        for sec in rules_sections
        if sec["section"].lower().strip() == section_name.lower().strip()
    ]
    if sections:
        return json.dumps(sections[0])
    return "Section not found. Prefer hybrid_search for official CoS PDF rules."


def search_rules(query: str) -> str:
    """Legacy JSONL keyword search — prefer hybrid_search for CoS PDFs."""
    query_lower = query.lower()
    matching_sections = []
    for sec in rules_sections:
        section_text = sec.get("section", "").lower()
        content = json.dumps(sec.get("content", "")).lower() if sec.get("content") else ""
        if query_lower in section_text or query_lower in content:
            matching_sections.append(
                {
                    "section": sec.get("section", ""),
                    "preview": str(sec.get("content", ""))[:500],
                }
            )
    if matching_sections:
        return json.dumps(matching_sections[:5])
    return "No matching sections found. Use hybrid_search instead."


def hybrid_search(
    query: str,
    doc_types: list[str] | None = None,
    generation: str | None = None,
    limit: int = 6,
) -> str:
    """Hybrid dense + BM25 search over CoS PDFs and curriculum text."""
    gen = _active_generation(generation)
    if not gen:
        return (
            "Entry year / curriculum generation unknown. "
            "Ask whether the student joined in 2024-or-earlier (legacy) or 2025-or-later (new), "
            "then call hybrid_search again with generation='legacy' or generation='2025'."
        )
    try:
        from backend.knowledge_service import format_hit_citation, hybrid_search as _hs

        hits = _hs(query, generation=gen, doc_types=doc_types, limit=limit or 6)
    except Exception as e:
        return f"Error running hybrid_search: {e}"
    if not hits:
        return f"No hybrid results for generation={gen}."
    blocks = [
        f"curriculum_generation={gen} (entry ≤2024 → legacy; ≥2025 → 2025)",
        f"results={len(hits)}",
        "",
    ]
    for i, hit in enumerate(hits, start=1):
        blocks.append(f"### Hit {i}")
        blocks.append(format_hit_citation(hit))
        blocks.append("")
    blocks.append(
        "Cite each factual claim with source filename + page (or URL for website hits)."
    )
    return "\n".join(blocks)


def search_courses(query: str, generation: str | None = None) -> str:
    """
    Searches for courses that match the query string in name or description.
    Optionally filter by curriculum generation (legacy | 2025).
    """
    from backend.models import Course, get_session
    from sqlmodel import select, or_

    query_lower = f"%{query.lower()}%"
    gen = _active_generation(generation)
    try:
        with get_session() as sess:
            conditions = [
                or_(
                    Course.name.ilike(query_lower),  # type: ignore[attr-defined]
                    Course.description.ilike(query_lower),  # type: ignore[attr-defined]
                    Course.code.ilike(query_lower),  # type: ignore[attr-defined]
                )
            ]
            if gen:
                conditions.append(Course.generation == gen)
            stmt = select(Course).where(*conditions).limit(10)
            results = sess.exec(stmt).all()
            if results:
                matching_courses = [
                    {
                        "code": c.code,
                        "name": c.name,
                        "credits": c.credits,
                        "generation": c.generation,
                        "academic_unit": c.academic_unit,
                        "source": c.source,
                        "description": (
                            (c.description or "")[:300] + "..."
                            if len(c.description or "") > 300
                            else (c.description or "")
                        ),
                    }
                    for c in results
                ]
                return json.dumps(matching_courses)
    except Exception as e:
        return f"An error occurred while searching courses: {str(e)}"
    return "No matching courses found."


def _clean_wikitext(text: str) -> str:
    """Strip metadata/embed wikitext markup; preserve wikilinks, bold/italic, headings, tables."""
    # Remove [[File:...]] and [[Image:...]] embeds (but keep other wikilinks intact)
    text = re.sub(r'\[\[(?:File|Image):[^\]]*\]\]', '', text, flags=re.IGNORECASE)
    # Remove {{template...}} blocks
    text = re.sub(r'\{\{[^{}]*\}\}', '', text)
    # Unwrap external links: [http://... label] -> label, bare [http://...] -> remove
    text = re.sub(r'\[https?://\S+\s+([^\]]+)\]', r'\1', text)
    text = re.sub(r'\[https?://\S+\]', '', text)
    # Collapse 3+ blank lines to 2
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def get_wiki_page(page_title: str, max_chars: int = 3000) -> str:
    """
    Fetches a page from the IITD community wiki (wiki.devclub.in) by its exact title.
    """
    try:
        site = mwclient.Site('wiki.devclub.in', path='/')
        page = site.pages[page_title]
        if not page.exists:
            return f"Page '{page_title}' not found on the wiki."
        text = _clean_wikitext(page.text())
        if len(text) > max_chars:
            return text[:max_chars] + f"\n\n[...content truncated at {max_chars} characters. Use a more specific query or request a section if more detail is needed.]"
        return text
    except Exception as e:
        return f"Error fetching wiki page '{page_title}': {str(e)}"


def search_wiki(query: str) -> str:
    """
    Searches the IITD community wiki (wiki.devclub.in) for pages matching the query.
    Returns up to 5 results with titles and text snippets.
    """
    try:
        site = mwclient.Site('wiki.devclub.in', path='/')
        raw_results = list(site.search(query, what='text', api_chunk_size=5, max_items=5))
        if not raw_results:
            return "No wiki pages found for that query."
        results = []
        for r in raw_results:
            title = r.get('title', '')
            snippet = r.get('snippet', '')
            # Strip HTML span tags from snippets (e.g. <span class="searchmatch">)
            snippet = re.sub(r'<[^>]+>', '', snippet).strip()
            results.append({"title": title, "snippet": snippet})
        return json.dumps(results, indent=2)
    except Exception as e:
        return f"Error searching the wiki for '{query}': {str(e)}"


# =====================
# TOOL SCHEMAS (OpenAI format)
# =====================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_course_data",
            "description": """Fetches detailed information about specific courses by their course codes.

WHEN TO USE: Use this tool ONLY when you have one or more specific course codes (e.g., COL100, MTL101, ELL201, COL1000).

DO NOT USE when:
- Searching for courses by topic/description → use search_courses instead
- Querying courses by department/slot/credits → use query_sqlite_db instead

INPUT: List of course codes (e.g., ["COL100", "MTL101"])
OUTPUT: JSON with course details (name, credits, description, prerequisites, generation,
academic_unit, learning_outcomes, source) and offerings from catalog_courses when available
(year, semester, instructor, slot).""",
            "parameters": {
                "type": "object",
                "properties": {
                    "course_codes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of course codes to look up (e.g., ['COL100', 'ELL101', 'COL1000'])"
                    }
                },
                "required": ["course_codes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_sqlite_db",
            "description": """Executes SQL SELECT queries on the courses database.

WHEN TO USE: Use when querying courses by structured fields like department, slot, credits, instructor, or year - NOT for topic-based searches.

SCHEMA:
- course(code, name, description, hours_lecture, hours_tutorial, hours_practical,
  credits, prereq, overlap, generation, academic_unit, learning_outcomes JSONB,
  source, source_url)
  generation: 'legacy' (≤2024 entry / 3-digit codes) | '2025' (≥2025 / often 4-digit)
  source: sqlite | curriculum_web | courses_iitd | pdf
- courseoffering(id, code, year, semester, instructor, slot)  -- legacy; prefer catalog_courses
- courseoverlap(id, code_1, code_2)
- semesters(code, label, classes_start, last_teaching_day, is_active)
  semester codes are YYTT (e.g. 2601 = Odd Sem 2026-27)
- catalog_courses(semester_code, course_code, course_data JSONB)
  course_data keys: courseCode, courseName, instructor, instructorEmail,
  instructors[{name,email}], totalCredits, creditStructure, slot{name,lectureTimingStr,...}

COMMON QUERIES:
1. Courses by department: SELECT code, name, credits, generation FROM course WHERE code LIKE 'CO%'
2. Slot this semester: SELECT course_code, course_data->>'courseName' AS name
   FROM catalog_courses WHERE course_data->'slot'->>'name' = 'A'
   AND semester_code = (SELECT code FROM semesters WHERE is_active LIMIT 1)
3. Courses by credits: SELECT code, name FROM course WHERE credits = 4
4. Course offerings: SELECT semester_code, course_data->>'instructor' AS instructor
   FROM catalog_courses WHERE course_code = 'COL100' ORDER BY semester_code DESC
5. Courses by instructor: SELECT course_code, semester_code FROM catalog_courses
   WHERE course_data->>'instructor' ILIKE '%Kumar%'
   OR course_data::text ILIKE '%Kumar%'
6. 2025-gen courses: SELECT code, name FROM course WHERE generation = '2025' AND code LIKE 'CO%'

DEPARTMENT PREFIXES: CO (CS), EL (EE), MC (ME), CV (CE), CL (CH), MT (Math), PY (Physics), CM (Chemistry), BB (Biotech), AP (Applied Mech), TX (Textile), DD (Design), HU/HS (HSS), MS (Materials), AI (AI), ES (Energy)

NOTE:
- Only SELECT queries allowed
- Prefer catalog_courses for instructors/slots/semester history; course table for descriptions/prereqs/CLOs
- Filter by generation when the student's curriculum generation is known
- Avoid SELECT * on course; exclude 'description' unless specifically needed""",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The SQL SELECT query to execute"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_programme_structure",
            "description": """Fetches the complete programme structure for a B.Tech/Dual Degree programme.

WHEN TO USE: When user asks about:
- Curriculum or course plan for a specific branch
- Recommended semester-wise courses
- Credit requirements for a degree
- Course categories (core, elective, open) for a programme

OUTPUT: JSON with credit requirements by category and semester-wise recommended course list.

PROGRAMME CODES:
B.Tech: AM1 (Applied Mech), BB1 (Biotech), CE1 (Civil), CH1 (Chemical), CS1 (CSE), EE1 (Electrical), EE3 (EE Power), ES1 (Energy), ME1 (Mechanical), ME2 (Production), MS1 (Materials), MT1 (Math & Computing), PH1 (Engg Physics), TT1 (Textile)
Dual Degree: CH7 (Chemical), CS5 (CSE), MT6 (Math & Computing)""",
            "parameters": {
                "type": "object",
                "properties": {
                    "programme_code": {
                        "type": "string",
                        "description": "The programme code to look up (e.g., 'CS1', 'EE1')"
                    },
                    "generation": {
                        "type": "string",
                        "enum": ["legacy", "2025"],
                        "description": "Curriculum generation; omit to use entry year"
                    }
                },
                "required": ["programme_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "hybrid_search",
            "description": """Primary retrieval for academic rules, CoS policies, and curriculum narrative.

Hybrid dense + BM25 over official CoS PDFs and curriculum.iitd.ac.in text.
Hard-gated by curriculum generation from year of joining:
- entry ≤2024 → legacy (CoS 2024 PDFs)
- entry ≥2025 → 2025 (CoS 2025 PDFs + curriculum website)

Returns snippets with source filename, page numbers, section path, and source_url.
ALWAYS cite those in your reply.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language or keyword query"
                    },
                    "doc_types": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["rule", "course", "programme"]
                        },
                        "description": "Optional document-type filter"
                    },
                    "generation": {
                        "type": "string",
                        "enum": ["legacy", "2025"],
                        "description": "Override generation if entry year unknown"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max hits (default 6)"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_rules_section",
            "description": """Fetches the full content of a specific rules section by exact name.

WHEN TO USE: When you know the exact section name for a policy/rule query.

COMMON SECTIONS (use exact names):
- Grading: "2.9 Grading System", "2.9.1 Grade points", "2.9.2 Description of grades"
- Credits: "2.2 Credit System", "2.3 Assignment of Credits to Courses"
- Registration: "3.1 Registration", "3.7 Add/Drop, Audit and Withdrawal of Courses"
- Attendance: "3.16 Attendance Rule"
- Limits: "3.13 Limits on Registration"
- Semester withdrawal: "3.8 Semester Withdrawal"
- UG requirements: "1.1.1 Overall Requirements: B.Tech."
- Dual degree: "1.1.3 Overall Requirements: Dual degree programmes"
- Probation: "1.6 Conditions for Continuation of Registration, Termination/Re-start, Probation"
- Branch change: "1.9 Change of Programme at the End of the First Year"
- Minors/Specializations: "2. CAPABILITY-LINKED OPTIONS FOR UNDERGRADUATE STUDENTS"
- PG requirements: "1.1 Degree Requirements" (in PG section)
- Ph.D.: "1.13 Doctor of Philosophy (Ph.D.) Regulations"

If unsure of exact section name, use search_rules first to find it.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "section_name": {
                        "type": "string",
                        "description": "The exact section name to retrieve (e.g., '2.1 Course Numbering Scheme')"
                    }
                },
                "required": ["section_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_rules",
            "description": """Searches rules/policy sections by keyword matching.

WHEN TO USE:
- When you don't know the exact section name
- As a fallback when get_rules_section returns "Section not found"
- For exploratory queries about policies

Returns top 5 matching sections with previews. After finding relevant sections, call get_rules_section with the exact section name to get full content.

EXAMPLES:
- search_rules("internship") → finds sections about semester leave, DPE internships
- search_rules("CGPA") → finds sections about grade calculation, requirements
- search_rules("minor") → finds minor degree options""",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to find relevant rules sections"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_courses",
            "description": """Searches courses by topic, keywords in name or description.

WHEN TO USE: When searching for courses about a specific topic (e.g., "machine learning", "data structures", "thermodynamics") rather than by code or department.

DO NOT USE when:
- You have a specific course code → use get_course_data
- Filtering by slot/credits/department → use query_sqlite_db

Returns top 10 matching courses with code, name, credits, generation, and description preview.
Covers both legacy CoS courses and courses.iitd.ac.in / curriculum.iitd.ac.in (2025) entries.

EXAMPLES:
- search_courses("machine learning") → finds AI/ML related courses
- search_courses("optimization", generation="2025") → 2025-gen optimization courses
- search_courses("database") → finds database-related courses""",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to find relevant courses"
                    },
                    "generation": {
                        "type": "string",
                        "enum": ["legacy", "2025"],
                        "description": "Optional curriculum generation filter; omit to use entry year"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_wiki_page",
            "description": """Fetches a page from the IITD community wiki (wiki.devclub.in) by its exact title.

WHEN TO USE: For questions about campus life, student resources, clubs, campus facilities, and general IITD info NOT covered by other tools

DO NOT USE for:
- Course details → use get_course_data / search_courses / query_sqlite_db
- Academic rules/policies → use get_rules_section / search_rules
- Programme structures → use get_programme_structure

If you don't know the exact page title, use search_wiki first.

FOLLOWING LINKS: The returned wikitext preserves [[Wikilink]] and [[Page|label]] syntax.
The page title inside [[ ]] can be passed directly to get_wiki_page to fetch that linked page.

KNOWN TOP LEVEL PAGE TITLES (use these exactly):
Hostels, Clubs_and_Societies, Student_Bodies, Buildings, Sports_Facilities,
Mess_and_Food, Placements, Internships, Scholarships, Library, Health_Services,
Transportation, Faculty_Directory, Important_Contacts, Rules_and_Regulations,
Fee_Structure, Courses, Departments, Centres, Schools, Academic_Calendar,
Grading_System, Main_Page""",
            "parameters": {
                "type": "object",
                "properties": {
                    "page_title": {
                        "type": "string",
                        "description": "Exact wiki page title (e.g., 'Hostels', 'Clubs_and_Societies')"
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return (default 3000)"
                    }
                },
                "required": ["page_title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_wiki",
            "description": """Searches the IITD community wiki (wiki.devclub.in) for pages matching the query.

WHEN TO USE:
- When you don't know the exact wiki page title
- For exploratory queries about campus life, facilities, or student resources
- As a fallback when get_wiki_page returns "Page not found"

Returns up to 5 results with page titles and text snippets.
After finding the relevant title, call get_wiki_page with that title to get the full content.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to find relevant wiki pages"
                    }
                },
                "required": ["query"]
            }
        }
    }
]

# Mapping of tool names to their implementations
TOOL_MAPPING = {
    "get_course_data": get_course_data,
    "query_sqlite_db": query_sqlite_db,
    "get_programme_structure": get_programme_structure,
    "hybrid_search": hybrid_search,
    "get_rules_section": get_rules_section,
    "search_rules": search_rules,
    "search_courses": search_courses,
    "get_wiki_page": get_wiki_page,
    "search_wiki": search_wiki,
}


def execute_tool(tool_name: str, arguments: dict) -> str:
    """
    Execute a tool by name with the given arguments.
    Returns the tool's response as a string.
    """
    if tool_name not in TOOL_MAPPING:
        return f"Error: Unknown tool '{tool_name}'"
    
    try:
        tool_func = TOOL_MAPPING[tool_name]
        return tool_func(**arguments)
    except Exception as e:
        return f"Error executing tool '{tool_name}': {str(e)}"

if __name__ == '__main__':
    search_wiki('ARIES')