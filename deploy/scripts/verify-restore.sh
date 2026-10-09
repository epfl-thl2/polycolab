#!/usr/bin/env bash
set -Eeuo pipefail

# A local, recoverable restore drill. It creates a uniquely named database,
# checks the migration and core table shape, and drops only that database after
# success (or keeps it when KEEP_RESTORE_DB=1 is requested).

usage() {
  cat <<'EOF'
Usage: verify-restore.sh --dump FILE --database-url URL [--manifest FILE] [--research-max-items N]
       [--artifacts-max-items N] [--credentials-max-items N] [--isolated-dependencies] [--dry-run]

DATABASE_URL may also be used instead of --database-url. The source and target
must be local PostgreSQL URLs. KEEP_RESTORE_DB=1 preserves the exact drill DB
for inspection; otherwise it is removed by name after verification. URLs with
query/fragment overrides or multiple database path segments are rejected.
--dry-run validates the URL's loopback host parsing without connecting to
PostgreSQL or requiring a dump file.
--manifest compares canonical state using RECOVERY_MANIFEST_HMAC_KEY before
cleanup, then checks restored research semantics with a default 1000-row bound.
--research-max-items enables the semantic check independently, or overrides its
bound (1-1000000). An incomplete scan fails verification and retains the database.
--artifacts-max-items and --credentials-max-items opt into restored artifact-byte
and credential-decryption checks with independent bounds (1-1000000). They require
--isolated-dependencies, confirming that the configured storage/key services are
the quiescent isolated restore, with read-only credentials and writers disabled.
No external dependency check is enabled by --manifest alone. The script overrides
only DATABASE_URL; operators must configure restored storage/key services explicitly.
Any restore or verification failure preserves the drill database.
EOF
}

dump=""
base_url="${DATABASE_URL:-}"
dry_run=false
manifest=""
check_research=false
research_max_items=1000
artifacts_max_items=""
credentials_max_items=""
isolated_dependencies=false
while (($#)); do
  case "$1" in
    --dump) dump="${2:?--dump requires a file}"; shift 2 ;;
    --database-url) base_url="${2:?--database-url requires a URL}"; shift 2 ;;
    --manifest) manifest="${2:?--manifest requires a file}"; check_research=true; shift 2 ;;
    --research-max-items) research_max_items="${2:?--research-max-items requires a bound}"; check_research=true; shift 2 ;;
    --artifacts-max-items) artifacts_max_items="${2:?--artifacts-max-items requires a bound}"; shift 2 ;;
    --credentials-max-items) credentials_max_items="${2:?--credentials-max-items requires a bound}"; shift 2 ;;
    --isolated-dependencies) isolated_dependencies=true; shift ;;
    --dry-run) dry_run=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[[ -n "$dump" && -n "$base_url" ]] || { usage >&2; exit 2; }
if [[ ! "$research_max_items" =~ ^[1-9][0-9]{0,6}$ ]] || ((research_max_items > 1000000)); then
  echo "Research verification bound must be 1-1000000" >&2
  exit 2
fi
for bound in "$artifacts_max_items" "$credentials_max_items"; do
  if [[ -n "$bound" ]]; then
    if [[ ! "$bound" =~ ^[1-9][0-9]{0,6}$ ]] || ((bound > 1000000)); then
      echo "Dependency verification bounds must be 1-1000000" >&2
      exit 2
    fi
  fi
done
if [[ -n "$artifacts_max_items" || -n "$credentials_max_items" ]]; then
  if [[ "$isolated_dependencies" != true ]]; then
    echo "Dependency checks require --isolated-dependencies and explicit restored service configuration" >&2
    exit 2
  fi
elif [[ "$isolated_dependencies" == true ]]; then
  echo "--isolated-dependencies requires at least one dependency check" >&2
  exit 2
fi
if [[ "$dry_run" != true && ! -f "$dump" ]]; then
  echo "Backup file does not exist: $dump" >&2
  exit 2
fi
[[ "${APP_ENV:-local}" == "local" ]] || { echo "Restore drill is local-only; set APP_ENV=local" >&2; exit 2; }

pg_url="${base_url/postgresql+psycopg:/postgresql:}"
pg_url="${pg_url/postgresql+asyncpg:/postgresql:}"
if [[ "$pg_url" != postgresql://* || "$pg_url" == *\?* || "$pg_url" == *\#* ]]; then
  echo "Refusing restore URL: require PostgreSQL URI without query/fragment overrides" >&2
  exit 2
fi
uri_path="${pg_url#postgresql://}"
database_name="${uri_path#*/}"
if [[ "$uri_path" == "$database_name" || ! "$database_name" =~ ^[a-zA-Z0-9_]+$ ]]; then
  echo "Refusing restore URL: require one explicit database path" >&2
  exit 2
fi
authority="${pg_url#*://}"
authority="${authority%%/*}"
authority="${authority%%\?*}"
# Remove URI userinfo without printing it. URI-encoded '@' remains part of the
# password; the final literal '@' is the userinfo/host separator.
host_port="${authority##*@}"
if [[ "$host_port" == \[*\]* ]]; then
  host_part="${host_port#\[}"
  host_part="${host_part%%\]*}"
  port_part="${host_port#*\]}"
  port_part="${port_part#:}"
else
  if [[ "$host_port" == *:* ]]; then
    host_part="${host_port%%:*}"
    port_part="${host_port#*:}"
  else
    host_part="$host_port"
    port_part=""
  fi
fi

if [[ "$host_port" == "::1" ]]; then
  host_part="::1"
  port_part=""
elif [[ "$host_port" =~ ^::1:([0-9]+)$ ]]; then
  host_part="::1"
  port_part="${BASH_REMATCH[1]}"
fi
if [[ -n "$port_part" && ! "$port_part" =~ ^[0-9]+$ ]]; then
  echo "Refusing restore drill: invalid local PostgreSQL port" >&2
  exit 2
fi
case "$host_part" in
  localhost|127.0.0.1|::1) ;;
  *) echo "Refusing restore drill against non-loopback host" >&2; exit 2 ;;
esac

if [[ "$dry_run" == true ]]; then
  echo "DRY RUN: validated loopback PostgreSQL host $host_part; target database name will use polycolab_restore_<timestamp>"
  exit 0
fi
command -v psql >/dev/null || { echo "psql is required" >&2; exit 127; }
command -v createdb >/dev/null || { echo "createdb is required" >&2; exit 127; }
command -v dropdb >/dev/null || { echo "dropdb is required" >&2; exit 127; }
if [[ -n "$manifest" ]]; then
  [[ -f "$manifest" ]] || { echo "Expected manifest file unavailable" >&2; exit 2; }
  command -v uv >/dev/null || { echo "uv is required for manifest comparison" >&2; exit 127; }
  [[ -n "${RECOVERY_MANIFEST_HMAC_KEY:-}" ]] || { echo "Manifest comparison key required" >&2; exit 2; }
fi
if [[ "$check_research" == true ]]; then
  command -v uv >/dev/null || { echo "uv is required for research verification" >&2; exit 127; }
fi
if [[ "$isolated_dependencies" == true ]]; then
  command -v uv >/dev/null || { echo "uv is required for dependency verification" >&2; exit 127; }
fi

suffix="$(date -u +%Y%m%d%H%M%S)_$$"
target_db="polycolab_restore_$suffix"
target_url="${pg_url%/*}/$target_db"
admin_url="${pg_url%/*}/postgres"
verification_complete=false
cleanup() {
  if [[ "$verification_complete" != true ]]; then
    echo "Restore/verification did not complete; no database was automatically removed. Inspect only $target_db." >&2
  elif [[ "${KEEP_RESTORE_DB:-0}" == 1 ]]; then
    echo "Keeping restore database $target_db (KEEP_RESTORE_DB=1)."
  else
    dropdb --if-exists --maintenance-db="$admin_url" "$target_db" || echo "Warning: could not remove exact drill database $target_db" >&2
  fi
}
trap cleanup EXIT

echo "Restoring into isolated local database $target_db"
"$(dirname "$0")/restore-postgres.sh" --dump "$dump" --database-url "$target_url"

tables="$(psql "$target_url" -Atqc "SELECT count(*) FROM pg_class WHERE relkind IN ('r','p') AND relnamespace = 'public'::regnamespace")"
[[ "$tables" =~ ^[0-9]+$ && "$tables" -gt 0 ]] || { echo "Restore contains no public tables" >&2; exit 1; }
psql "$target_url" -v ON_ERROR_STOP=1 -Atqc "SELECT version_num FROM alembic_version" >/dev/null
psql "$target_url" -v ON_ERROR_STOP=1 -Atqc "SELECT count(*) FROM projects" >/dev/null
if [[ -n "$manifest" ]]; then
  repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
  # The token/key stay in the environment, and private module diagnostics are
  # suppressed. Only its bounded content-free report reaches the operator.
  DATABASE_URL="$target_url" uv run --frozen --directory "$repo_root/src/backend" \
    python -m polycolab.recovery_integrity compare --expected "$manifest" 2>/dev/null || {
      echo "Canonical integrity verification failed; drill database retained" >&2
      exit 1
    }
fi
if [[ "$check_research" == true ]]; then
  repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
  DATABASE_URL="$target_url" uv run --frozen --directory "$repo_root/src/backend" \
    python -m polycolab.recovery_dependencies research --isolated-restore \
    --max-items "$research_max_items" 2>/dev/null || {
      echo "Research integrity verification failed or incomplete; drill database retained" >&2
      exit 1
    }
fi
for dependency in artifacts credentials; do
  case "$dependency" in
    artifacts) bound="$artifacts_max_items" ;;
    credentials) bound="$credentials_max_items" ;;
  esac
  if [[ -n "$bound" ]]; then
    repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
    DATABASE_URL="$target_url" uv run --frozen --directory "$repo_root/src/backend" \
      python -m polycolab.recovery_dependencies "$dependency" --isolated-restore \
      --max-items "$bound" 2>/dev/null || {
        echo "Restored $dependency verification failed or incomplete; drill database retained" >&2
        exit 1
      }
  fi
done
verification_complete=true
echo "Restore verification passed: $tables public tables and migration metadata are readable."
