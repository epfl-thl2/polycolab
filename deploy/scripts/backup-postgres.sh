#!/usr/bin/env bash
set -Eeuo pipefail

# Create a PostgreSQL custom-format backup. The script intentionally writes only
# below the caller-selected directory and never removes an existing backup.
# Encrypted backups stream directly to age without a plaintext dump on disk.
# Production/staging callers must provide an encryption recipient.

usage() {
  cat <<'EOF'
Usage: backup-postgres.sh [backup-directory]

Environment:
  DATABASE_URL                    PostgreSQL URL, or use PGSERVICE instead
  PGSERVICE / PGSERVICEFILE        libpq service configuration (preferred)
  APP_ENV                         local, staging, or production (default: local)
  BACKUP_ENCRYPTION_RECIPIENT      age recipient; required outside local
  BACKUP_KEEP_DAYS                Retention hint only; pruning is a separate,
                                  explicitly scoped operation (default: 14)
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

backup_dir="${1:-deploy/.local/backups/postgres}"
database_url="${DATABASE_URL:-}"
app_env="${APP_ENV:-local}"
keep_days="${BACKUP_KEEP_DAYS:-14}"
dump_args=(--format=custom --no-owner --no-acl)
if [[ -n "$database_url" && -n "${PGSERVICE:-}" ]]; then
  echo "Configure DATABASE_URL or PGSERVICE, not both" >&2
  exit 2
elif [[ -n "$database_url" ]]; then
  pg_url="${database_url/postgresql+psycopg:/postgresql:}"
  pg_url="${pg_url/postgresql+asyncpg:/postgresql:}"
  dump_args+=("$pg_url")
elif [[ -z "${PGSERVICE:-}" ]]; then
  echo "DATABASE_URL or PGSERVICE must be set (values are never logged)" >&2
  exit 2
fi

[[ "$keep_days" =~ ^[0-9]+$ ]] || { echo "BACKUP_KEEP_DAYS must be an integer" >&2; exit 2; }
case "$app_env" in
  local|staging|production) ;;
  *) echo "APP_ENV must be local, staging or production" >&2; exit 2 ;;
esac
if command -v sha256sum >/dev/null; then
  checksum_command=(sha256sum)
elif command -v shasum >/dev/null; then
  checksum_command=(shasum -a 256)
else
  echo "sha256sum or shasum is required" >&2
  exit 127
fi
if [[ "$app_env" != "local" && -z "${BACKUP_ENCRYPTION_RECIPIENT:-}" ]]; then
  echo "BACKUP_ENCRYPTION_RECIPIENT is required for $app_env backups" >&2
  exit 2
fi
if [[ -n "${BACKUP_ENCRYPTION_RECIPIENT:-}" ]]; then
  command -v age >/dev/null || { echo "age is required when encryption is enabled" >&2; exit 127; }
fi
command -v pg_dump >/dev/null || { echo "pg_dump is required" >&2; exit 127; }

echo "Creating PostgreSQL backup (destination: $backup_dir; retention hint: ${keep_days}d)"
umask 077
mkdir -p -- "$backup_dir"
backup_dir="$(cd -- "$backup_dir" && pwd -P)"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
# A private per-run directory prevents same-second/concurrent invocations from
# overwriting one another. Cleanup knows only this invocation's exact paths.
run_dir="$(mktemp -d "$backup_dir/polycolab-$timestamp.XXXXXX")"
dump_name="postgres.dump"
if [[ -n "${BACKUP_ENCRYPTION_RECIPIENT:-}" ]]; then
  dump_name="$dump_name.age"
fi
dump_file="$run_dir/$dump_name"
partial="$run_dir/$dump_name.partial"
checksum="$dump_file.sha256"
complete=false
cleanup() {
  if [[ "$complete" != true ]]; then
    rm -f -- "$partial" "$dump_file" "$checksum" "$run_dir/COMPLETE"
    rmdir -- "$run_dir" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ -n "${BACKUP_ENCRYPTION_RECIPIENT:-}" ]]; then
  # pipefail rejects a failed/truncated pg_dump even if age exits successfully.
  # Upstream diagnostics can contain database names/content; do not relay them
  # into operational logs. Report a normalized failure instead.
  if ! pg_dump "${dump_args[@]}" 2>/dev/null |
    age --encrypt --recipient "$BACKUP_ENCRYPTION_RECIPIENT" > "$partial" 2>/dev/null; then
    echo "Backup dump or encryption failed; incomplete output will be removed" >&2
    exit 1
  fi
else
  if ! pg_dump "${dump_args[@]}" > "$partial" 2>/dev/null; then
    echo "Backup dump failed; incomplete output will be removed" >&2
    exit 1
  fi
fi
[[ -s "$partial" ]] || { echo "Backup output is empty" >&2; exit 1; }
mv -- "$partial" "$dump_file"
# Use a relative filename so verification still works after moving the bundle.
(cd -- "$run_dir" && "${checksum_command[@]}" "$dump_name" > "$dump_name.sha256")
printf '%s\n' 'polycolab-postgres-backup-v1' > "$run_dir/COMPLETE"
complete=true
echo "Completed backup bundle: $run_dir"

echo "No retention pruning was performed. Review and delete individual expired files only after confirming policy."
