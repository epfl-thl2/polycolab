#!/usr/bin/env bash
set -Eeuo pipefail

# Operator-run, quiescent capture. Does not stop or start services itself.
if [[ "${1:-}" == --help ]]; then
  printf '%s\n' 'Usage: backup-recovery-set.sh EXISTING_PRIVATE_BACKUP_DIRECTORY' \
    'Requires RECOVERY_WRITERS_QUIESCED=yes, RECOVERY_GARAGE_STOPPED=yes, PGSERVICE,' \
    'BACKUP_ENCRYPTION_RECIPIENT, RECOVERY_GARAGE_METADATA_DIR, RECOVERY_GARAGE_DATA_DIR,' \
    'RECOVERY_KEY_MATERIAL_DIR, RELEASE_SHA and RECOVERY_SCHEMA_HEAD.'
  exit 0
fi
fail() { printf '%s\n' "Research backup: $1" >&2; exit 1; }
[[ $# == 1 ]] || fail invalid_arguments
[[ "${RECOVERY_WRITERS_QUIESCED:-}" == yes && "${RECOVERY_GARAGE_STOPPED:-}" == yes ]] || fail quiescence_required
[[ -n "${PGSERVICE:-}" && -z "${DATABASE_URL:-}" ]] || fail private_pgservice_required
[[ -n "${BACKUP_ENCRYPTION_RECIPIENT:-}" ]] || fail encryption_required
[[ "${RELEASE_SHA:-}" =~ ^[a-f0-9]{7,64}$ ]] || fail invalid_release
[[ "${RECOVERY_SCHEMA_HEAD:-}" =~ ^[a-zA-Z0-9_]{1,128}$ ]] || fail invalid_schema_head
for tool in pg_dump age tar; do command -v "$tool" >/dev/null || fail missing_tool; done
if command -v sha256sum >/dev/null; then
  checksum=(sha256sum)
elif command -v shasum >/dev/null; then
  checksum=(shasum -a 256)
else
  fail checksum_tool_required
fi

# Reject broad, relative and symlink roots; paths must name prepared offline
# volume mounts / exported key state, not the machine's general data directory.
validate_directory() {
  local candidate="$1"
  [[ "$candidate" == /* && "$candidate" != / && -d "$candidate" && ! -L "$candidate" ]] || fail invalid_directory
  [[ "$(cd -- "$candidate" && pwd -P)" == "$candidate" ]] || fail noncanonical_directory
  [[ "$candidate" != "${HOME:-}" ]] || fail broad_directory
}
backup_root="$1"
metadata_dir="${RECOVERY_GARAGE_METADATA_DIR:-}"
data_dir="${RECOVERY_GARAGE_DATA_DIR:-}"
key_dir="${RECOVERY_KEY_MATERIAL_DIR:-}"
for directory in "$backup_root" "$metadata_dir" "$data_dir" "$key_dir"; do
  validate_directory "$directory"
done
for source in "$metadata_dir" "$data_dir" "$key_dir"; do
  [[ "$backup_root/" != "$source/"* && "$source/" != "$backup_root/"* ]] || fail overlapping_destination
done
[[ "$metadata_dir/" != "$data_dir/"* && "$data_dir/" != "$metadata_dir/"* ]] || fail overlapping_sources
[[ "$key_dir/" != "$metadata_dir/"* && "$metadata_dir/" != "$key_dir/"* ]] || fail overlapping_sources
[[ "$key_dir/" != "$data_dir/"* && "$data_dir/" != "$key_dir/"* ]] || fail overlapping_sources

umask 077
run_dir="$(mktemp -d "$backup_root/research-recovery.XXXXXXXX")"
# Preserve partial ciphertext for diagnosis; never mark it complete or delete
# operator data on failure. No secret-bearing command diagnostics are relayed.
trap 'printf "%s\n" "Research backup interrupted; incomplete set retained" >&2; exit 130' INT
trap 'printf "%s\n" "Research backup interrupted; incomplete set retained" >&2; exit 143' TERM
if ! pg_dump --format=custom --no-owner --no-acl 2>/dev/null |
  age --encrypt --recipient "$BACKUP_ENCRYPTION_RECIPIENT" > "$run_dir/postgres.dump.age" 2>/dev/null; then
  fail database_capture_failed
fi
capture_directory() {
  local source="$1" output="$2"
  # No dereference flag: symlinks are archived as links, never followed.
  if ! tar -C "$source" -cf - . 2>/dev/null |
    age --encrypt --recipient "$BACKUP_ENCRYPTION_RECIPIENT" > "$run_dir/$output" 2>/dev/null; then
    fail volume_capture_failed
  fi
}
capture_directory "$metadata_dir" garage-metadata.tar.age
capture_directory "$data_dir" garage-data.tar.age
capture_directory "$key_dir" key-material.tar.age
for component in postgres.dump.age garage-metadata.tar.age garage-data.tar.age key-material.tar.age; do
  [[ -s "$run_dir/$component" ]] || fail empty_component
done
(
  cd -- "$run_dir"
  printf 'format=polycolab-recovery-v1\nrelease=%s\nschema=%s\n' "$RELEASE_SHA" "$RECOVERY_SCHEMA_HEAD"
  "${checksum[@]}" postgres.dump.age garage-metadata.tar.age garage-data.tar.age key-material.tar.age
) | age --encrypt --recipient "$BACKUP_ENCRYPTION_RECIPIENT" > "$run_dir/manifest.age" 2>/dev/null || fail manifest_failed
printf '%s\n' polycolab-recovery-v1 > "$run_dir/COMPLETE"
printf '%s\n' 'Research backup: captured encrypted recovery set; writers remain stopped' "$run_dir"
