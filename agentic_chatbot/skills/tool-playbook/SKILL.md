---
name: tool-playbook
description: Tool-selection playbook for course, policy, programme, wiki, and SQL questions. Use when choosing which backend tool to call.
---

## Tool Selection

For a specific course code, use `get_course_data(["CODE"])`.

For structured course queries by field (department, slot, credits, instructor, year), use `query_sqlite_db()` with a SELECT query. Prefer `catalog_courses` for slots, instructors, and semester offerings. Prefer `course` for descriptions, prerequisites, credits, source URLs, and generation.

For topic or description search across courses, use `search_courses(query, generation?)`.

For official rules, policies, curriculum narrative, and known/unknown CoS sections:
- Use `search_cos(query)` when you need relevant snippets and section references.
- Use `list_cos_sections(document?, depth?)` when you need the CoS table of contents / headers.
- Use `get_cos_section(section_ref)` when you need the full text of a known section.
- `hybrid_search` remains available for broad retrieval across CoS PDFs plus curriculum web/course/programme text.

For structured degree plans and recommended semester courses, use `get_programme_structure(programme_code, generation?)`.

For campus-life, facilities, student bodies, and DevClub wiki information not covered by official academic sources, use `search_wiki` then `get_wiki_page`.

Always cite URLs or PDF filename + page numbers returned by tools.

## Examples

User: "What is COL351 about?"
Use `get_course_data(["COL351"])`.

User: "Are there courses on machine learning?"
Use `search_courses("machine learning")`.

User: "What CS courses are offered in slot A?"
Use `query_sqlite_db` against `catalog_courses`.

User: "What is the attendance rule?"
Use `search_cos("attendance rule")`, then `get_cos_section(section_ref)` if a full section is needed.

User: "What should a CS1 student take in third semester?"
Use `get_programme_structure("CS1")`.
