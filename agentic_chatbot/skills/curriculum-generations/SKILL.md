---
name: curriculum-generations
description: Full legacy versus 2025+ curriculum routing details. Use before answering rules, programme, or CoS questions where entry year matters.
---

## Curriculum Generations

IIT Delhi currently has two curriculum generations by year of entry:

- `legacy`: entry year 2024 and earlier. Use CoS 2024 PDFs, legacy programme structures, and legacy course descriptions.
- `2025`: entry year 2025 onwards. Use CoS 2025 PDFs and structured data from `curriculum.iitd.ac.in` / `courses.iitd.ac.in`.

The user context may include `Curriculum Generation`, `year_of_joining`, and programme code. If the generation is unknown and the question depends on rules, curriculum structure, course codes, or degree requirements, ask whether the student joined in 2024-or-earlier or 2025-or-later before answering.

Do not mix generations unless the user explicitly asks for a comparison. When using retrieval tools, pass the relevant generation or let the tool infer it from user context.

Course code clue:
- `COL380`, `MTL101`, `ELL201`: likely legacy 3-digit style.
- `COL1000`, `COL1101`: likely 2025+ 4-digit style.

If a user gives only a branch, derive programme code carefully, then confirm if uncertain.
