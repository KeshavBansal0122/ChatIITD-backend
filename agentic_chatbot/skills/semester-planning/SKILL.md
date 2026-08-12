---
name: semester-planning
description: Workflow for course, semester, OC, workload, prerequisite, and slot planning. Use when the user asks to plan courses.
---

## Semester Planning Workflow

Start with the user's programme structure using `get_programme_structure(programme_code)`. Identify the recommended next-semester courses and category requirements before suggesting electives.

Use the user's `courses_done` context when present. Do not recommend courses already completed unless the user asks about retakes or overlap.

For each candidate course:
- Check prerequisites with `get_course_data`.
- Check current or recent offerings with `query_sqlite_db` on `catalog_courses`.
- Check slot conflicts using the `slot` fields in `catalog_courses.course_data`.
- Prefer source-backed course descriptions from `get_course_data`, `search_courses`, or SQL queries that include `source_url`.

For OC or elective planning, ask one focused clarifying question if preferences are missing: workload tolerance, preferred area, slot constraints, or target category.

Keep the first response compact unless the user asks for a full multi-semester plan. Avoid dumping every possible elective.
