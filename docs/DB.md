# ChatIITD database guide

This document describes every Postgres table used by the ChatIITD backend, where the data comes from, and how to refresh it for a new semester.

Vector search (Qdrant) is intentionally omitted — that stack will be overhauled separately.

---

## Quick map

| Concern | Tables | Source |
|--------|--------|--------|
| Auth / profile | `user`, `oauthstate` | DevClub OIDC (`auth.devclub.in`) |
| User course checklist | `usercourse` | Manual profile edits (+ defaults from programme JSON) |
| Chat | `chat`, `message`, `message_history` | App runtime |
| Uploaded PDFs metadata | `document` | Admin uploads |
| Course descriptions / prereqs | `course`, `courseoverlap` | Seeded from `courses.sqlite` |
| Legacy offerings | `courseoffering` | Older CSV (`sources/courses_offered.csv`) — prefer catalog |
| **Semester catalog + instructors** | `semesters`, `catalog_courses` | IITD Courses_Offered CSV / Classgrid API |
| **Student enrollments** | `student_enrollments`, `course_rosters` | IITD LDAP (`ldapweb.iitd.ac.in`) |
| Hostel overlay | `students` | `student_hostels.csv` (optional) |
| **LLM usage / BYOK** | `llm_usage`, `user_llm_credentials` | OpenRouter shared pool + encrypted user keys |

SQL migrations live in `db/migrations/`. Import tools live in `sources/classgrid_catalog/`.

---

## Migrations

| File | Creates |
|------|---------|
| `db/migrations/001_classgrid_catalog.sql` | `semesters`, `catalog_courses` (+ indexes) |
| `db/migrations/002_student_enrollments.sql` | `student_enrollments`, `course_rosters`, `students` |
| `db/migrations/003_llm_usage_and_credentials.sql` | `llm_usage`, `user_llm_credentials` |

App tables (`user`, `chat`, …, `course`, …) are created by SQLModel `init_db()` / `SQLModel.metadata.create_all`.

Apply Classgrid-style migrations via the import scripts (they run the SQL idempotently), or manually:

```bash
psql "$DATABASE_URL" -f db/migrations/001_classgrid_catalog.sql
psql "$DATABASE_URL" -f db/migrations/002_student_enrollments.sql
```

---

## Table reference

### App / auth

#### `user`
Logged-in ChatIITD accounts.

| Column | Notes |
|--------|--------|
| `oauth_id` | DevClub OIDC subject |
| `email`, `name`, `picture` | From OIDC |
| `kerberos`, `entry_number`, `hostel`, `department`, `category` | OIDC claims (kerberos also derived from email local-part) |
| `role` | `user` / `admin` |

**Source:** DevClub OIDC userinfo on login (`backend/auth.py`). Not refreshed from LDAP.

#### `oauthstate`
Temporary PKCE `code_verifier` rows during OAuth. Ephemeral.

#### `usercourse`
Courses the student marked as completed on their profile.

| Column | Notes |
|--------|--------|
| `user_id` | FK-ish to `user.id` |
| `course_code` | Uppercase code |
| `semester` | Programme semester index `1…10` (not YYTT) |

**Source:** LDAP sync into `usercourse` via `sources/classgrid_catalog/sync_enrollments_to_usercourse.py` (default for registered students). Also `PUT /user/courses` from the Profile UI; “Load Defaults” fills from `sources/programme_structures/*.json`.

#### `chat`, `message`, `message_history`
Chat sessions and transcripts. `message_history` stores full agent/tool turns as JSON text.

#### `document`
Metadata for admin-uploaded PDFs (file on disk; chunking/Qdrant out of scope here).

---

### Legacy course catalogue (descriptions)

#### `course`
Static course dictionary: name, description, L-T-P hours, credits, prereq/overlap text.

**Source:** Seeded once from `backend/courses.sqlite` when empty (`models._seed_courses_from_sqlite`). Good for chatbot descriptions; **not** per-semester instructors.

#### `courseoffering`
Older per-term offering rows (`year` like `2024-25`, `semester` 1/2, instructor, slot).

**Source:** `sources/courses_offered.csv` via `sources/import_offerings.py`.

Prefer **`catalog_courses`** for new work (instructors, slots, YYTT history).

#### `courseoverlap`
Pairs of mutually exclusive course codes. Seeded from `courses.sqlite`.

---

### Classgrid-compatible catalog (course history + instructors)

#### `semesters`
One row per IITD term code **YYTT** (e.g. `2601` = Sem 1 of 2026–27, `2502` = Sem 2 of 2025–26).

| Column | Notes |
|--------|--------|
| `code` | PK, YYTT |
| `label` | Human label |
| `classes_start`, `last_teaching_day` | Approximate from code meta (or calendar import) |
| `is_active` | At most one `true` (partial unique index) |
| `academic_calendar` | JSONB (optional; not required for catalog) |
| `catalog_etag`, `catalog_updated_at` | Set on catalog import |

#### `catalog_courses`
Per-semester offering. Instructors live **inside** `course_data` JSONB (no separate professors table — same as Classgrid).

**Primary key:** `(semester_code, course_code)`

**`course_data` shape (Classgrid):**

```json
{
  "courseCode": "COL106",
  "courseName": "DATA STRUCTURES AND ALGORITHMS",
  "semesterCode": "2502",
  "totalCredits": 5,
  "creditStructure": "3.0-0.0-4.0",
  "instructor": "…",
  "instructorEmail": "…@….iitd.ac.in",
  "instructors": [{ "name": "…", "email": "…" }],
  "slot": {
    "name": "F",
    "lectureTimingStr": "TThF 11:00-12:00",
    "lectureTiming": "…",
    "tutorialTiming": null,
    "labTiming": null
  },
  "currentStrength": "0",
  "lectureHall": null
}
```

**Sources:**

1. Canonical CSVs: `sources/courses_offered/<YYTT>.csv` (`2201`–`2601`)
2. Mirrored copies: `sources/classgrid_catalog/historical/` + `Courses_Offered_<YYTT>.csv`
3. Live refresh: Classgrid `GET https://classgrid.devclub.in/api/catalog` (active semester only)

**Scripts:**

```bash
# Parse + import all local CSVs; activate newest or --activate=2601
.venv/bin/python sources/classgrid_catalog/import_catalog.py --activate=2601

# Dry-run parse only
.venv/bin/python sources/classgrid_catalog/import_catalog.py --dry-run

# Refresh active semester from Classgrid API (server-side; Classgrid has no CORS)
.venv/bin/python sources/classgrid_catalog/sync_from_classgrid_api.py --activate
```

To refresh CSV files from the Classgrid repo:

```bash
cp ../classgrid/data/courses_offered_historical/*.csv sources/courses_offered/
cp ../classgrid/data/Courses_Offered.csv sources/courses_offered/2601.csv
```

Parser port: `parse_catalog_csv.py` ← Classgrid `scripts/db/parse_catalog_csv.js`.

---

### Student enrollments (who took what)

#### `student_enrollments`
| Column | Notes |
|--------|--------|
| `semester_code` | YYTT |
| `kerberos` | Student id only (`aa1234567` or `abc123456`) |
| `course_code` | Uppercase |

**PK:** `(semester_code, kerberos, course_code)`

#### `course_rosters`
Inverted view with display names (same LDAP scrape).

| Column | Notes |
|--------|--------|
| `semester_code`, `course_code`, `student_kerberos` | PK |
| `student_name` | From LDAP HTML |

#### `students`
Optional hostel overlay only — **not** the enrollment source of truth.

| Column | Notes |
|--------|--------|
| `kerberos` | PK |
| `hostel` | From CSV |

**Source of enrollments:** IITD LDAP web UI  
`https://ldapweb.iitd.ac.in/LDAP/courses/` (intranet / VPN). Intermediate JSON under `sources/classgrid_catalog/ldap_exports/<YYTT>/` (gitignored — PII).

**Scripts:**

```bash
# VPN required for fetch
./sources/classgrid_catalog/fetch_student_enrollments.sh 2601 --fetch-only
./sources/classgrid_catalog/fetch_student_enrollments.sh 2601 --import

# Or one-shot fetch+import
./sources/classgrid_catalog/fetch_student_enrollments.sh 2601

# Every semester that exists both in our `semesters` table and on LDAP
./sources/classgrid_catalog/fetch_student_enrollments.sh --all-available

# Hostels (optional)
.venv/bin/python sources/classgrid_catalog/import_student_hostels.py
```

Python entrypoint: `import_student_data.py` (port of Classgrid `import_student_data.js`).

**Join for “student course history”:**

```sql
SELECT s.label, c.course_code, c.course_data->>'courseName' AS name,
       c.course_data->>'instructor' AS instructor
FROM student_enrollments e
JOIN catalog_courses c
  ON c.semester_code = e.semester_code AND c.course_code = e.course_code
JOIN semesters s ON s.code = e.semester_code
WHERE lower(e.kerberos) = 'mt6240685'
ORDER BY s.code DESC;
```

Helpers: `backend/catalog_db.py` (`get_student_enrollments`, `get_course_roster`, `search_instructors`, …).

**Profile courses (`usercourse`):** sync from LDAP enrollments with:

```bash
.venv/bin/python sources/classgrid_catalog/sync_enrollments_to_usercourse.py
```

Creates `kerberos@iitd.ac.in` user stubs if needed, maps YYTT → programme semester 1–10 (entry year from kerberos chars `[3:5]`, matching Classgrid `kerberosMeta`), excludes the active semester (completed courses only). Use `--replace` after fixing mapping logic or refreshing LDAP. Login also auto-seeds empty profiles via `seed_user_courses_from_ldap`.

---

### LLM usage + BYOK credentials

#### `llm_usage`
Prompt + completion token accounting for the rolling window.

| Column | Notes |
|--------|--------|
| `user_id` | Set for logged-in users |
| `device_fingerprint` | SHA-256 of server-signed `chatiitd_did` cookie (guests / abuse binding). **Not** a MAC — browsers cannot expose MACs; cookie is HMAC-signed so clients cannot forge IDs without `DEVICE_ID_SECRET` |
| `prompt_tokens`, `completion_tokens`, `total_tokens` | From provider `usage` |
| `provider`, `model` | openrouter / openai / anthropic / … |

Env: `RATE_LIMIT_TOKENS`, `RATE_LIMIT_WINDOW_HOURS`, `RATE_LIMIT_GUEST_TOKENS`, `RATE_LIMIT_BYOK_EXEMPT`.

#### `user_llm_credentials`
Encrypted user API keys (AES-256-GCM). Raw keys are never returned by the API.

| Column | Notes |
|--------|--------|
| `api_key_ciphertext`, `api_key_nonce` | Envelope encryption via `CREDENTIALS_ENCRYPTION_KEY` |
| `key_fingerprint` | Short hash for UI only |
| `provider`, `base_url`, `model` | openai / anthropic (native SDK) / openrouter / google / groq / custom |

Profile UI: **AI provider** section. Scope remains IITD-only even with BYOK.

Example: activate **2602** when the new Courses_Offered sheet is out.

1. **Drop CSV into the repo**
   - Current: `sources/classgrid_catalog/Courses_Offered_2602.csv`
   - Or keep historical copies as `historical/2602.csv` after the term ends.

2. **Import catalog (+ instructors)**
   ```bash
   cd backend
   .venv/bin/python sources/classgrid_catalog/import_catalog.py --semester=2602 --activate=2602
   # OR if you only have Classgrid online:
   .venv/bin/python sources/classgrid_catalog/sync_from_classgrid_api.py --activate
   ```

3. **Fetch enrollments (VPN)**
   ```bash
   ./sources/classgrid_catalog/fetch_student_enrollments.sh 2602
   ```
   Re-run mid-semester as add/drop settles. Import replaces that semester’s enrollment/roster rows.

4. **Optional hostels refresh**
   ```bash
   .venv/bin/python sources/classgrid_catalog/import_student_hostels.py --file=...
   ```

5. **Sanity checks**
   ```sql
   SELECT code, label, is_active,
          (SELECT count(*) FROM catalog_courses c WHERE c.semester_code = s.code) AS courses
   FROM semesters s ORDER BY code DESC;

   SELECT semester_code, count(*) AS rows, count(DISTINCT kerberos) AS students
   FROM student_enrollments GROUP BY 1 ORDER BY 1 DESC;
   ```

### LDAP availability notes

LDAP course pages are only published for some terms. As of writing, prefixes seen on `gpaliases.html` included e.g. `2302`, `2401`–`2403`, `2501`–`2503`, `2601` — older catalog-only terms (`2201`, `2202`, `2301`) may have **catalog** history without **enrollment** dumps. Summer codes (`xx03`) need a `semesters` stub before import if you want them.

**Loaded snapshot (Aug 2026):** enrollments imported for `2302`, `2401` (sparse — LDAP pages largely empty), `2402`, `2501`, `2502`, `2601`. Catalog history covers `2201`–`2601`.

---

## External APIs (server-side only)

Classgrid (`https://classgrid.devclub.in`) exposes public read APIs but **sends no CORS headers**. Call them from the ChatIITD backend (or scripts), never from the browser.

| Endpoint | Use |
|----------|-----|
| `GET /api/health` | Active semester + counts |
| `GET /api/semesters` | Term list + catalog counts |
| `GET /api/catalog` | Active-semester course_data (incl. instructors) |
| `GET /api/courses/:code/offerings` | Course history (catalog) |
| `GET /api/courses/:code/students?semester=` | Roster for a term |
| `GET /api/students/:kerberos/offerings` | One student’s history |
| `GET /api/instructors/search?q=` | Instructor search |

Env: `CLASSGRID_BASE_URL` (default `https://classgrid.devclub.in`).

LDAP remains the **bulk** enrollment source; Classgrid student APIs are per-student / per-course.

---

## Docker (seed at image build)

Catalog CSVs, instructors, LDAP enrollment JSON, hostels, and `usercourse` stubs are loaded **while building** the Postgres image (`Dockerfile.postgres`). The dump is written to `/docker-entrypoint-initdb.d/` and applied the first time the postgres volume is empty.

```bash
cd backend
# ldap_exports/ must exist locally (gitignored PII) for a full seed
docker compose build postgres
# Fresh volume required to re-apply the dump after a rebuild:
docker compose down -v
docker compose up -d
```

Build args:
- `SEED_ACTIVATE` (default `2601`)
- `SEED_SKIP_ENROLLMENTS=1` — catalog-only image (no LDAP JSON required)

Orchestrator: `sources/classgrid_catalog/seed_all.py` (also usable against a running DB).

---

## Directory layout (data + tools)

```
backend/
  Dockerfile.postgres        ← multi-stage: seed DB → SQL dump in image
  docker/build_postgres_seed.sh
  requirements-seed.txt
  db/migrations/
    001_classgrid_catalog.sql
    002_student_enrollments.sql
    003_llm_usage_and_credentials.sql
  docs/DB.md                 ← this file
  sources/
    courses_offered/         ← canonical Courses_Offered CSVs (<YYTT>.csv)
    classgrid_catalog/
      parse_catalog_csv.py
      parse_instructors.py
      import_catalog.py
      seed_all.py            ← full DB seed (Docker + local)
      sync_from_classgrid_api.py
      import_student_data.py
      sync_enrollments_to_usercourse.py
      fetch_student_enrollments.sh
      import_student_hostels.py
      student_kerberos.py
      semester_code_meta.py
      historical/*.csv       ← mirror of courses_offered/
      Courses_Offered_XXXX.csv
      student_hostels.csv
      ldap_exports/          ← gitignored PII JSON (required for Docker full seed)
    courses_offered.csv     ← legacy offerings import
    programme_structures/   ← profile “Load Defaults”
  courses.sqlite            ← seed for course / overlaps
```

---

## What we deliberately skip (for now)

From Classgrid / campus data: room allotments, occupied slots, venues, FCM tokens, course policies, attendance, planner events. Revisit if product needs them.
