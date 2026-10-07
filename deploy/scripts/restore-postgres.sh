#!/usr/bin/env bash
set -Eeuo pipefail

# Restore one dump into a new, explicitly named database. This script refuses
# production and refuses ambiguous database names so a restore drill cannot
# overwrite the application database by accident.

usage() {
  cat <<'EOF'
Usage: restore-postgres.sh --dump FILE --database-url URL [--replace] [--dry-run]

The target database name must match polycolab_restore_<suffix>. Existing target
databases are never touched unless --replace is supplied. --replace is intended
only for that exact restore database and still requires RESTORE_CONFIRM=YES.
Encrypted .age files must be decrypted to a mode-600 temporary file first.
Connection URLs must have one database path and no query or fragment overrides.
--dry-run validates the target URL and prints the exact maintenance/database
names without connecting to PostgreSQL.
EOF
}

dump=""
target_url=""
replace=false
dry_run=false
while (($#)); do
  case "$1" in
    --dump) dump="${2:?--dump requires a file}"; shift 2 ;;
    --database-url) target_url="${2:?--database-url requires a URL}"; shift 2 ;;
    --replace) replace=true; shift ;;
    --dry-run) dry_run=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$dump" && -n "$target_url" ]] || { usage >&2; exit 2; }
if [[ "$dry_run" != true && ! -f "$dump" ]]; then
  echo "Backup file does not exist: $dump" >&2
  exit 2
fi
[[ "${APP_ENV:-local}" == "local" ]] || { echo "Restore drill is local-only; set APP_ENV=local" >&2; exit 2; }

pg_url="${target_url/postgresql+psycopg:/postgresql:}"
pg_url="${pg_url/postgresql+asyncpg:/postgresql:}"
if [[ "$pg_url" != postgresql://* || "$pg_url" == *\?* || "$pg_url" == *\#* ]]; then
  echo "Refusing restore URL: require PostgreSQL URI without query/fragment overrides" >&2
  exit 2
fi
uri_path="${pg_url#postgresql://}"
target_db="${uri_path#*/}"
[[ "$target_db" =~ ^polycolab_restore_[a-z0-9_]+$ ]] || {
  echo "Refusing target database; use one polycolab_restore_<suffix> path" >&2
  exit 2
}

admin_url="${pg_url%/*}/postgres"
if [[ "$dry_run" == true ]]; then
  echo "DRY RUN: maintenance database URL is redacted; target database is $target_db"
  exit 0
fi
command -v pg_restore >/dev/null || { echo "pg_restore is required" >&2; exit 127; }
command -v psql >/dev/null || { echo "psql is required" >&2; exit 127; }
command -v createdb >/dev/null || { echo "createdb is required" >&2; exit 127; }
command -v dropdb >/dev/null || { echo "dropdb is required" >&2; exit 127; }
# Check the archive before any destructive replacement. This checks readability,
# not provenance or full restorability; use only a trusted verified backup.
if ! pg_restore --list "$dump" >/dev/null 2>&1; then
  echo "Backup archive validation failed; target was not changed" >&2
  exit 1
fi
if ! exists="$(psql "$admin_url" -Atqc "SELECT 1 FROM pg_database WHERE datname = '$target_db'" 2>/dev/null)"; then
  echo "Could not check restore target; target was not changed" >&2
  exit 1
fi
if [[ "$exists" != "" && "$exists" != 1 ]]; then
  echo "Unexpected restore target response; target was not changed" >&2
  exit 1
fi
if [[ "$exists" == 1 ]]; then
  if [[ "$replace" != true || "${RESTORE_CONFIRM:-}" != YES ]]; then
    echo "Target database exists. Use --replace with RESTORE_CONFIRM=YES to replace only $target_db." >&2
    exit 2
  fi
  dropdb --if-exists --maintenance-db="$admin_url" "$target_db"
fi

createdb --maintenance-db="$admin_url" "$target_db"
pg_restore --exit-on-error --no-owner --no-acl --dbname="$pg_url" "$dump"
echo "Restored $dump into $target_db. It was not deleted; inspect or drop only this exact database when finished."
