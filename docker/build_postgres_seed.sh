#!/usr/bin/env bash
# Start a temporary Postgres inside the image build, seed it, dump SQL for initdb.
set -euo pipefail

export POSTGRES_USER="${POSTGRES_USER:-chatiitd}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-chatiitd_dev}"
export POSTGRES_DB="${POSTGRES_DB:-chatiitd}"
export PGDATA="${PGDATA:-/var/lib/postgresql/data}"
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DB}"
export PGPASSWORD="${POSTGRES_PASSWORD}"
export PYTHONPATH="/app"
export PATH="/opt/venv/bin:${PATH}"

mkdir -p /seed

# Official entrypoint initializes PGDATA then starts the server.
docker-entrypoint.sh postgres &
postgres_pid=$!

echo "[build_seed] waiting for postgres…"
for _ in $(seq 1 60); do
  if pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"

echo "[build_seed] running seed_all.py…"
cd /app

EXPORT_ROOT="${SEED_EXPORT_ROOT:-/app/sources/classgrid_catalog/ldap_exports}"
has_exports=0
if [[ -d "$EXPORT_ROOT" ]]; then
  for d in "$EXPORT_ROOT"/*/studentCourses.json; do
    if [[ -f "$d" ]]; then
      has_exports=1
      break
    fi
  done
fi

SEED_ARGS=(--activate="${SEED_ACTIVATE:-2601}" --out-dir="$EXPORT_ROOT")

if [[ "${SEED_SKIP_ENROLLMENTS:-0}" == "1" ]]; then
  echo "[build_seed] SEED_SKIP_ENROLLMENTS=1 — catalog only"
  SEED_ARGS+=(--skip-enrollments)
elif [[ "${SEED_REQUIRE_ENROLLMENTS:-0}" == "1" ]]; then
  echo "[build_seed] SEED_REQUIRE_ENROLLMENTS=1 — failing if LDAP JSON missing"
  SEED_ARGS+=(--require-enrollments)
elif [[ "$has_exports" -eq 0 ]]; then
  # ldap_exports/ is gitignored (PII). Deploy builds usually have catalog only.
  echo "[build_seed] no LDAP JSON under $EXPORT_ROOT — seeding catalog without enrollments"
  echo "[build_seed] (copy ldap_exports locally or set SEED_REQUIRE_ENROLLMENTS=1 to enforce)"
  SEED_ARGS+=(--skip-enrollments)
else
  echo "[build_seed] found LDAP JSON under $EXPORT_ROOT — importing enrollments"
fi

python sources/classgrid_catalog/seed_all.py "${SEED_ARGS[@]}"

echo "[build_seed] dumping database…"
pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" --no-owner --no-acl "$POSTGRES_DB" \
  > /seed/01_chatiitd_seed.sql

echo "[build_seed] stopping postgres…"
if command -v gosu >/dev/null 2>&1; then
  gosu postgres pg_ctl -D "$PGDATA" -m fast -w stop
else
  su -s /bin/bash postgres -c "pg_ctl -D '$PGDATA' -m fast -w stop"
fi
# Drop runtime data so the final image only carries the SQL dump for initdb
rm -rf "${PGDATA:?}/"*

echo "[build_seed] dump ready ($(wc -c < /seed/01_chatiitd_seed.sql) bytes)"
