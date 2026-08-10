# Deploying ChatIITD while preserving scraped data

The scraped corpus lives in **Postgres** (courses, programmes, catalog, enrollments)
and **Qdrant** (`knowledge` collection). Git holds scrapers + source files so you can
rebuild; production should prefer restoring DB/Qdrant dumps instead of re-scraping.

## What to preserve

| Store | Contains | How to ship |
|-------|----------|-------------|
| Postgres | `course`, `programme*`, `catalog_courses`, `semesters`, enrollments, users/chats | `pg_dump` / Docker volume |
| Qdrant | Hybrid RAG chunks (`knowledge`) | `snapshots/knowledge.snapshot` or volume |
| Optional git sources | CoS PDFs, `courses_iitd/`, `curriculum_2025/` | Rebuild path only |

Do **not** run `docker compose down -v` (or delete the Postgres/Qdrant volumes) if you
want to keep live data.

## 1. Export from the machine that has the data

```bash
cd backend
set -a && source .env && set +a

# Postgres (schema + data)
mkdir -p backups
pg_dump "$DATABASE_URL" --format=custom --file=backups/chatiitd_$(date +%Y%m%d).dump

# Or plain SQL:
# pg_dump "$DATABASE_URL" --file=backups/chatiitd_$(date +%Y%m%d).sql

# Qdrant knowledge snapshot (for compose qdrant-init restore)
export QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
.venv/bin/python chunking/export_knowledge_snapshot.py
# → snapshots/knowledge.snapshot
```

Copy to the VPS:

```bash
scp backups/chatiitd_YYYYMMDD.dump user@vps:/path/to/backend/backups/
scp snapshots/knowledge.snapshot user@vps:/path/to/backend/snapshots/
```

## 2. Deploy app code

```bash
# Backend
git pull
# set production .env (DATABASE_URL, QDRANT_URL, ADMIN_PASSWORD, OIDC, …)
# Frontend: build with matching VITE_BACKEND_URL / VITE_FRONTEND_URL
```

Apply schema migrations **without** wiping data:

```bash
psql "$DATABASE_URL" -f db/migrations/001_classgrid_catalog.sql
psql "$DATABASE_URL" -f db/migrations/002_student_enrollments.sql
psql "$DATABASE_URL" -f db/migrations/003_llm_usage_and_credentials.sql
psql "$DATABASE_URL" -f db/migrations/004_curriculum.sql
```

(`seed_all.py` / `Dockerfile.postgres` are for **empty** DBs. Skip them when restoring.)

## 3. Restore Postgres on the VPS

**A. Existing named volume (preferred)**  
If the compose Postgres volume already has your data, only pull code + migrate. Done.

**B. Fresh volume + dump restore**

```bash
# Start empty Postgres once, then:
pg_restore --clean --if-exists --no-owner --dbname="$DATABASE_URL" backups/chatiitd_YYYYMMDD.dump
# For plain SQL: psql "$DATABASE_URL" -f backups/chatiitd_YYYYMMDD.sql
```

**C. Seeded image** (`Dockerfile.postgres`)  
Only use when the volume is empty and you accept whatever was baked at image
build time (catalog/LDAP at build). It will **not** overwrite an existing volume.

## 4. Restore Qdrant knowledge

Place `snapshots/knowledge.snapshot`, then:

```bash
# Compose path: qdrant-init runs snapshots/restore.py when the snapshot exists
docker compose up -d qdrant
docker compose up --no-deps qdrant-init

# Or rebuild from sources (slow; needs PDFs + MiniLM):
# .venv/bin/python chunking/build_knowledge_index.py --recreate
```

## 5. Verify

```bash
psql "$DATABASE_URL" -c "SELECT generation, count(*) FROM course GROUP BY 1;"
psql "$DATABASE_URL" -c "SELECT count(*) FROM catalog_courses;"
curl -s "$QDRANT_URL/collections/knowledge" | jq '.result.points_count'
```

Expect on the order of: ~5k courses (legacy + 2025), catalog offerings, ~12k
knowledge points (if you exported after the latest index build).

## 6. Admin portal

Set `ADMIN_PASSWORD` in backend `.env`. UI: `/admin`.

## Rebuild from scraped sources (only if dumps are lost)

```bash
python sources/classgrid_catalog/seed_all.py --activate=2601
python sources/courses_iitd/import_courses_iitd.py
python sources/curriculum_2025/import_curriculum.py
python chunking/build_knowledge_index.py --recreate
python chunking/export_knowledge_snapshot.py
```

Scrapers (`scrape_*.py`, `download_cos_pdfs.py`) hit live IITD sites; prefer dumps.
