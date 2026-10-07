# Local artifact storage

This Garage configuration supports local artifact storage and integration tests.
The shared Docker Compose model also uses this configuration for application storage.

Persistent Docker volumes retain data across container restarts.
The configuration has one storage node.
It does not establish replication, backup/restore, or production durability.

Run from the repository root in a dedicated shell:

```sh
export GARAGE_RPC_SECRET="$(openssl rand -hex 32)"
export GARAGE_DEFAULT_ACCESS_KEY="GK$(openssl rand -hex 16)"
export GARAGE_DEFAULT_SECRET_KEY="$(openssl rand -hex 32)"
export GARAGE_DEFAULT_BUCKET=polycolab-artifacts
export COMPOSE_PROJECT_NAME=polycolab-platform-artifacts
docker compose -f deploy/garage/compose.yaml up -d --wait
docker compose -f deploy/garage/compose.yaml port garage 3900
```

Use a distinct project name for each worktree.
The S3 endpoint uses a randomly assigned loopback port by default.
Set `POLYCOLAB_GARAGE_PORT` if you need a fixed port.
RPC listens on loopback inside the container.
This configuration enables no admin or website service.
Clients use region `garage` and path-style SigV4 with the explicit bucket/access/secret above.

Keep these values private.
Retain them for reuse of this local data.

Do not print resolved Compose configuration into diagnostics, because it includes environment secrets.
Generating new keys is not a rotation procedure for an existing bucket.

Run this command to stop and remove containers.
It preserves local storage volumes:

```sh
docker compose -f deploy/garage/compose.yaml down
```

Do not add `--volumes` for storage you intend to keep.
The opt-in [integration tests](../../tests/execution/README.md) create a unique temporary project, verify this exact profile and remove only their own disposable volumes.

The image is pinned by version and digest.
Its configuration uses the documented [environment overrides](https://garagehq.deuxfleurs.fr/documentation/reference-manual/configuration/) and [single-node initialization](https://garagehq.deuxfleurs.fr/documentation/quick-start/), checked on 2026-09-07.
Application metadata must govern immutable identities and staging garbage collection.
Do not configure bucket expiry on committed artifact bytes.
