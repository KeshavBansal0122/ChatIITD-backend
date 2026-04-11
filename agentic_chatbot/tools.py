"""
Tools for the IIT Delhi Academic Chatbot.
These are plain Python functions with OpenAI-compatible tool schemas.
"""

import json
from pathlib import Path
from backend.courses_db import run_select_query, get_courses_by_codes, get_offerings_for_codes

# Get the directory containing this file (agentic_chatbot/)
_THIS_DIR = Path(__file__).parent.resolve()
# Get the backend directory (parent of agentic_chatbot/)
_BACKEND_DIR = _THIS_DIR.parent

# Paths to static data files (rules and programme structures — not in DB)
_SOURCES_DIR = _BACKEND_DIR / "sources"
_JSONL_DIR = _SOURCES_DIR / "jsonl"
_PROGRAMME_DIR = _SOURCES_DIR / "programme_structures"


# Load static documents (rules only — courses/offerings come from PostgreSQL)
def read_jsonl(filename):
    res = []
    with open(filename, 'r') as f:
        for line in f:
            res.append(json.loads(line))
    return res


rules_sections = read_jsonl(_JSONL_DIR / 'all_rules.jsonl')

# Load programme prompt
programme_prompt = ''
with open(_PROGRAMME_DIR / 'prompt.md', 'r') as f:
    programme_prompt = f.read()


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


def get_programme_structure(programme_code: str) -> str:
    """
    Fetches the programme structure for a given programme code.
    """
    programme_code = programme_code.upper().strip()
    programme_file = _PROGRAMME_DIR / f'{programme_code}.json'
    try:
        with open(programme_file, 'r') as f:
            programme_data = f.read()
        return programme_prompt + "\n\n" + programme_data
    except FileNotFoundError:
        return "Programme code not found."


def get_rules_section(section_name: str) -> str:
    """
    Fetches a specific section from the rules collection.
    """
    sections = [sec for sec in rules_sections if sec['section'].lower().strip() == section_name.lower().strip()]
    print(f'---get_rules_section called with section_name="{section_name}"---')
    print("Found sections:")
    print(sections)
    if sections:
        return json.dumps(sections[0])
    else:
        return "Section not found."


def search_rules(query: str) -> str:
    """
    Searches for rules sections that contain the query string.
    Returns matching sections based on keyword matching.
    """
    query_lower = query.lower()
    matching_sections = []
    
    for sec in rules_sections:
        section_text = sec.get('section', '').lower()
        content = json.dumps(sec.get('content', '')).lower() if sec.get('content') else ''
        
        if query_lower in section_text or query_lower in content:
            matching_sections.append({
                'section': sec.get('section', ''),
                'preview': str(sec.get('content', ''))[:500] + '...' if len(str(sec.get('content', ''))) > 500 else str(sec.get('content', ''))
            })
    
    if matching_sections:
        return json.dumps(matching_sections[:5])  # Return top 5 matches
    return "No matching sections found."


def search_courses(query: str) -> str:
    """
    Searches for courses that match the query string in name or description.
    """
    from backend.models import Course, get_session
    from sqlmodel import select, or_

    query_lower = f"%{query.lower()}%"
    try:
        with get_session() as sess:
            stmt = (
                select(Course)
                .where(
                    or_(
                        Course.name.ilike(query_lower),       # type: ignore[attr-defined]
                        Course.description.ilike(query_lower), # type: ignore[attr-defined]
                        Course.code.ilike(query_lower),        # type: ignore[attr-defined]
                    )
                )
                .limit(10)
            )
            results = sess.exec(stmt).all()
            if results:
                matching_courses = [
                    {
                        "code": c.code,
                        "name": c.name,
                        "credits": c.credits,
                        "description": (c.description or "")[:300] + "..." if len(c.description or "") > 300 else (c.description or ""),
                    }
                    for c in results
                ]
                return json.dumps(matching_courses)
    except Exception as e:
        return f"An error occurred while searching courses: {str(e)}"
    return "No matching courses found."


# =====================
# TOOL SCHEMAS (OpenAI format)
# =====================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_course_data",
            "description": """Fetches detailed information about specific courses by their course codes.

WHEN TO USE: Use this tool ONLY when you have one or more specific course codes (e.g., COL100, MTL101, ELL201).

DO NOT USE when:
- Searching for courses by topic/description → use search_courses instead
- Querying courses by department/slot/credits → use query_sqlite_db instead

INPUT: List of course codes (e.g., ["COL100", "MTL101"])
OUTPUT: JSON with course details (name, credits, description, prerequisites) and offerings (year, semester, instructor, slot)""",
            "parameters": {
                "type": "object",
                "properties": {
                    "course_codes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of course codes to look up (e.g., ['COL100', 'ELL101'])"
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
- course(code, name, description, hours_lecture, hours_tutorial, hours_practical, credits, prereq, overlap)
- courseoffering(id, code, year, semester, instructor, slot)
- courseoverlap(id, code_1, code_2)

COMMON QUERIES:
1. Courses by department: SELECT code, name, credits FROM course WHERE code LIKE 'CO%'
2. Courses by slot: SELECT c.code, c.name FROM course c JOIN courseoffering o ON c.code = o.code WHERE o.slot = 'A'
3. Courses by credits: SELECT code, name FROM course WHERE credits = 4
4. Course offerings: SELECT * FROM courseoffering WHERE code = 'COL100'
5. Courses by instructor: SELECT code FROM courseoffering WHERE instructor LIKE '%Kumar%'

DEPARTMENT PREFIXES: CO (CS), EL (EE), MC (ME), CV (CE), CL (CH), MT (Math), PY (Physics), CM (Chemistry), BB (Biotech), AP (Applied Mech), TX (Textile), DD (Design), HU/HS (HSS), MS (Materials), AI (AI), ES (Energy)

NOTE: 
- Only SELECT queries allowed
- Avoid SELECT * on course; exclude 'description' field unless specifically needed""",
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
                    }
                },
                "required": ["programme_code"]
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

Returns top 10 matching courses with code, name, credits, and description preview.

EXAMPLES:
- search_courses("machine learning") → finds AI/ML related courses
- search_courses("optimization") → finds optimization courses across departments
- search_courses("database") → finds database-related courses""",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to find relevant courses"
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
    "get_rules_section": get_rules_section,
    "search_rules": search_rules,
    "search_courses": search_courses,
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
