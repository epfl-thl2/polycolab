#!/usr/bin/env bash
set -Eeuo pipefail

# Forward Compose global options verbatim, including private env files and profiles.
mode="${1:-}"
case "$mode" in
  build|pull|reuse) shift ;;
  *) printf '%s\n' 'Usage: bash deploy/scripts/deploy-stack.sh build|pull|reuse [COMPOSE OPTIONS]' >&2; exit 2 ;;
esac
compose=(docker compose "$@")
"${compose[@]}" config --quiet

# A renamed Garage must never share live storage with its predecessor.
# Retiring old containers requires checking their data and taking a backup first.
existing_services="$("${compose[@]}" ps --all --format '{{.Service}}')"
while IFS= read -r service; do
  case "$service" in
    api|garage|migrate|community|execution-reconciler)
      printf '%s\n' 'Legacy Compose containers found. Follow the deployment upgrade instructions before starting this stack.' >&2
      exit 1 ;;
  esac
done <<< "$existing_services"

services="$("${compose[@]}" config --services)"
applications=(collaboration core)
while IFS= read -r service; do
  if [[ "$service" == worker ]]; then applications+=(worker); fi
done <<< "$services"

# Prepare images before interrupting the existing application.
case "$mode" in
  build) "${compose[@]}" build "${applications[@]}" ;;
  pull) "${compose[@]}" pull ;;
esac
"${compose[@]}" stop worker core
"${compose[@]}" up -d --wait postgres object-storage
"${compose[@]}" run --rm --no-deps -T core python -m polycolab.operations.migrate
# Failure above leaves core stopped. Never start it against a failed migration.
"${compose[@]}" up -d --wait --force-recreate "${applications[@]}"
