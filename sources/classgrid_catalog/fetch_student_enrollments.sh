#!/usr/bin/env bash
# Fetch IITD LDAP student lists and optionally import into ChatIITD Postgres.
#
# LDAP (ldapweb.iitd.ac.in) is only reachable on IITD intranet or VPN.
#
#   1. Connect to IITD VPN.
#   2. Fetch JSON locally (no DB needed):
#        ./sources/classgrid_catalog/fetch_student_enrollments.sh 2601 --fetch-only
#   3. Import into Postgres:
#        ./sources/classgrid_catalog/fetch_student_enrollments.sh 2601 --import
#
# One-shot on VPN with local Postgres:
#   ./sources/classgrid_catalog/fetch_student_enrollments.sh 2601
#
# All catalog semesters present on LDAP:
#   ./sources/classgrid_catalog/fetch_student_enrollments.sh --all-available

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON="${BACKEND_ROOT}/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    echo "Missing venv python at $PYTHON" >&2
    exit 1
fi

if [[ -f "${BACKEND_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${BACKEND_ROOT}/.env"
    set +a
fi

ARGS=()
if [[ "${1:-}" == "--all-available" ]]; then
    ARGS+=(--all-available)
    shift || true
elif [[ -n "${1:-}" && "${1:-}" != --* ]]; then
    ARGS+=(--semester="$1")
    shift || true
else
    echo "Usage: $0 <SEMESTER| --all-available> [--fetch-only|--import|--dry-run]" >&2
    exit 1
fi

MODE=both
for arg in "$@"; do
    case "$arg" in
        --fetch-only) MODE=fetch ;;
        --import) MODE=import ;;
        --dry-run) ARGS+=(--dry-run) ;;
        -h|--help)
            sed -n '2,20p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown option: $arg" >&2
            exit 1
            ;;
    esac
done

case "$MODE" in
    fetch) ARGS+=(--fetch-only) ;;
    import) ARGS+=(--from-json) ;;
esac

cd "$BACKEND_ROOT"
exec "$PYTHON" sources/classgrid_catalog/import_student_data.py "${ARGS[@]}"
