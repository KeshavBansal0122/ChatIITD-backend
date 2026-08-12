---
name: minor-programmes
description: Workflow for minor, specialization, and capability-linked undergraduate options. Use for minor planning questions.
---

## Minor / Capability-Linked Options

For minor or specialization questions, first retrieve the relevant official section:

1. Use `search_cos("minor capability-linked options undergraduate")`.
2. If a relevant `section_ref` is returned, call `get_cos_section(section_ref)` for the full rule text.
3. Cite the returned CoS source and page range.

Do not produce a full four-semester plan until the user confirms scope. Ask one or two focused questions when needed:
- Current semester / entry year.
- Target department or sub-area.
- Courses already completed or OC credits already used.

For course lists, combine official rules with `search_courses` and `query_sqlite_db` to check current offerings, slots, and prerequisites.
