# External agent API

Humans issue, reveal, list, and revoke account-wide agent API keys through `/api/v1/account/agent-keys`. Key creation requires only a name. Each key is directly owned by its owner and has request and write limits plus an expiry.

`GET /api/v1/me` reports current identity and budgets. `GET /api/v1/projects?scope=member` lists accessible projects. `GET /api/v1/projects/{project_id}` reads project metadata.

For Basic projects, `GET /api/v1/projects/{project_id}/files` lists current files. POST to the same path with `action: read`, `write`, `rename`, or `delete`. Reads and mutations return content identity. Replacing, moving, or deleting an existing file requires its `expected_digest`; a stale value returns a conflict. A new file omits that value.

Current membership grants read access. Owner or editor membership in an active project grants writes. File requests reserve budget atomically and revalidate authority after acquiring the filesystem lock. A failed mutation may still consume its reservation, preventing retries from bypassing limits.

These keys do not grant access to conversations, account administration, membership management, Git worktrees, or Collaborative endpoints. They do not carry research contribution/review flags or create research runs. Old tool capabilities are revoked during the removal migration.

Send credentials only to the configured origin, never through redirects or URLs. The served [agent skill](../../skills/polycolab/SKILL.md) describes the file workflow.
