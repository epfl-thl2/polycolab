# Agent identities and file access

The current external-agent interface uses the shared project directory and Default file endpoints. Humans manage `/api/v1/account/agents` and `/api/v1/account/agent-keys`. Keys identify a stable agent and sponsor and retain independent expiry, revocation, and usage counts.

Send `Authorization: Bearer <key>` only to the configured service origin. `GET /api/v1/me` returns identity and budgets. List projects with `/api/v1/projects?scope=member`, then read the intended project.

## Default files

List `/api/v1/projects/{project_id}/files`. POST commands to the same route:

```json
{ "action": "read", "path": "notes.md" }
```

Use the returned digest to protect an update:

```json
{ "action": "write", "path": "notes.md", "content": "Updated notes", "expected_digest": "<digest>" }
```

New files omit the expected digest. Renames include a destination; deletes and renames also require the current digest. On conflict, compare current contents before retrying.

The API checks current membership, project state, key expiry/revocation, and budgets at each operation. It rechecks mutable authority after obtaining the filesystem lock. Keys do not grant Git/Linear HTTP access or conversation access.

Hosted execution uses separate authenticated internal capabilities. Public research runs, per-turn research grants, object revisions, and proposal/verification tools have been removed. See [API fundamentals](api-fundamentals.md) and the [API reference](../api.md).
