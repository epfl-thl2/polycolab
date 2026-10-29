# HTTP API

FastAPI defines the versioned `/api/v1` contract. `pnpm run api:contract` exports OpenAPI and regenerates the browser client; neither output is edited manually.

The maintained API covers accounts, project discovery and membership, Default files, Git worktrees, Linear collaboration, LaTeX builds, artifacts, external identities and keys, hosted sessions, direct chat, and the agent library.

Public project reads expose metadata. Membership protects files. External agent keys can use the project directory and Default file API with current sponsor permissions and atomic request/mutation budgets. Account and membership mutations require human authentication.

Private `/internal/v1` routes authenticate workers and run capabilities. They are excluded from the public API description. Workers have no database credential.

Removed research, catalogue, commons, publication, proposal, history/profile, and verification endpoints return 404. No compatibility API recreates those services.

## Artifacts

Upload bytes to `POST /api/v1/projects/{project_id}/artifacts`, declaring `sha256`, `byte_length`, and optional `media_type`. A verified upload commits immediately to that project. Read metadata or `/content` beneath the same project path. Reads recheck current membership and hosted-output access where applicable. Upload authorization is rechecked after storage verification.

No research attachment, publication link, or object revision is required. Hosted output exports retain their authenticated agent-run routes.
