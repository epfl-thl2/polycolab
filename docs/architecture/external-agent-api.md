# Shared research API and agent keys

Polycolab exposes the same core `/api/v1` resources to browser sessions, human OIDC tokens and external-agent bearer keys.
Anonymous callers can read public research.
Agents contribute with their sponsor's current workspace authority.
Public Library contributions additionally require explicit key opt-in.

## Shared URLs

The development cutover removes every `/api/v1/public/*` endpoint without aliases or redirects.
Anonymous and authenticated callers use the same resource URLs.
Collections default to `scope=public`.
Workspace-scoped discovery, records, and attempt lists require `scope=member` and an authorized `workspace_id`.
Exact reads resolve the caller's current membership before choosing a member or public projection.
Explicit invalid credentials fail even when a resource is public.

Catalogue and Library reads use `/catalogue` and `/library`, publication manifests use `/publications/{id}`, and assurance reads use `/assurance/{object_version_id}`.
Community aggregate counts use `/community/{entry_id}`.
Human personal state uses `/community/{entry_id}/me`.
Recovery calls use `/account/email/verify` and `/auth/password-reset/request` or `/auth/password-reset/confirm` under `/api/v1`.

Browser workspace lists share `/workspaces?scope=public|member`, with public as the anonymous default and member as the signed-in default.
Both scopes share detail URLs.
The old standalone public HTML documents are removed: Library pages live under `/library/{id}` and exact records under `/commons/records/{object_version_id}`.
These application pages require JavaScript.
Deploy matching API and web builds together.
The URL cutover needs no database migration.

## Core modules

| Module    | Resources                                                                                                     | Purpose                                                                        |
| --------- | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Access    | `/me`, `/account/agents`, `/account/agent-keys`                                                               | Inspect authority. Humans manage stable agent identities and keys.             |
| Discovery | `/search`, `/workspaces`, existing catalogue routes                                                           | Find public/member research and reviewed Library statements.                   |
| Research  | `/objects`, `/objects/{id}/versions`, `/versions/{id}`, `/objects/{id}/contributions`, comments and relations | Read exact sources and save independently attributed contributions.            |
| Evidence  | `/artifacts`, `/attachments`, `/versions/{id}/attachments`                                                    | Stage actor-owned bytes and attach verified evidence to exact object versions. |
| History   | `/activity`, `/activity/workspaces`, `/objects/{id}/activity`, `/contributions/{id}`                          | Inspect immutable saved changes with live visibility filtering.                |
| Profiles  | `/profiles/{user_id}`, `/agent-profiles/{agent_id}`, each with `/activity`                                    | Public authored and sponsored contributions by stable identity.                |

The API reference nests these sections under six core modules.
Human account, workspace and publication administration follows them.
Hosted agents, execution, verification and historical external-run reads remain separate.
This change does not rename all existing research and catalogue URLs.

## Identity and authority

In **Settings → Agent API keys**, create a named agent or select an existing one, then issue a key.
A stable agent identity belongs to one sponsor.
Name changes and key rotation preserve its attribution.
Multiple keys can serve the same agent.
Keys keep separate expiration, revocation, request and mutation budgets.

`POST /account/agent-keys` requires `agent_id` and a key name.
`allow_library_contributions` defaults to `false` and is immutable for the key.
Opt-in permits supporting contributions to existing Library statements, including comments, relations and evidence.
It does not permit admitting statements, changing official formulations or publishing private research.
Those operations remain human-only.
Existing keys receive no new public-write authority.

Send `Authorization: Bearer <key>`.
Never put secrets in a URL.
Invalid explicit Authorization fails instead of falling back to a cookie or anonymous identity.
Keys follow the sponsor's current and future workspace memberships.
Agent keys grant no access to personal notes, conversations, key management or membership administration.
`GET /me` reports identity and remaining budgets without consuming request budget.

## Independent writes

Independent writes require no external execution record, input manifest, start call or close call.
For example, `POST /api/v1/objects` accepts:

```json
{
  "destination": { "kind": "workspace", "workspace_id": "<uuid>" },
  "snapshot": {
    "kind": "NOTE",
    "content": {
      "title": "An observation",
      "content_md": "The boundary case needs a separate argument.",
      "assumptions_md": "None stated",
      "reported_outcome": null,
      "explanation_md": null
    },
    "structural_relationships": [],
    "change_summary": null
  }
}
```

For a Library contribution, replace `destination` with `{"kind":"library","statement_object_version_id":"<exact official version uuid>"}`.
Include an explicit `ATTACHMENT` structural relationship targeting that same `target_object_version_id`.
The contribution does not change the formulation.
Proof sketches and attempts retain their required typed structure and pinned inputs.

New versions require `expected_current_object_version_id` and a complete `snapshot`.
Omitted fields do not inherit.
An explicit empty relationship set removes those pins from the new version, without changing previous versions.

Humans and agents send `Idempotency-Key` on object creation, new versions, comments, relations and attachment writes.
Responses have one shape:

```json
{
  "contribution_id": "<uuid>",
  "outputs": [{ "entity_type": "OBJECT_VERSION", "entity_id": "<uuid>" }],
  "replayed": false
}
```

Create responses include both object and object-version outputs.
Resolve returned IDs through resource reads.
Do not assume a mutation response contains the resource.
Keep the same body and key for a lost-response retry.
A changed payload under the same actor/operation/key conflicts.
The API checks authorization before replay.

Committed retries do not consume another mutation, including across key rotation for the same stable agent.
A different agent cannot revise another agent's work.

`GET /versions/{id}` returns exact content, assumptions, proof/attempt structure, attachments and stable author attribution.
`GET /objects/{id}/contributions` returns readable research attached to its exact statement versions.
Version responses include a predecessor ID only when that predecessor is readable in the caller's authorized scope.
Publishing a version does not expose its private predecessor to anonymous readers or keys without workspace membership.

## Evidence

`POST /api/v1/artifacts` accepts binary bytes with `sha256`, `byte_length`, `media_type`, and exactly one of `workspace_id` or `statement_object_version_id` as query parameters.
Supply an `Idempotency-Key` to recover the same staged identity after an interrupted response.
Staging stays private to the human or stable agent that uploaded it, including across that agent's key rotation.
Matching bytes do not grant another actor access.

Optional upload provenance uses `source_object_version_id`.
`POST /attachments` accepts `artifact_id`, `object_version_id`, `role`, and optional `attempt_object_version_id`, and commits verified bytes and an exact version binding in one transaction.
Library staging can attach only to the selected statement or its attached research.
Staging alone creates no activity.
Uncommitted or expired uploads remain subject to garbage collection.
Uncommitted bytes are not served.

Attachment lists use the same explicit object-version fields and accept an `object_version_id` filter.
Public artifact metadata projects these names from the frozen release.
Stored publication JSON and retry digests are not rewritten.

## History and public profiles

Saved object versions, comments, relations, authored summaries, progress updates, committed evidence, Library formulations and private publication create durable source-referenced activity in the canonical transaction.
Events store source IDs and attribution rather than copying request content.
Failed requests and retries do not create another event.
External execution logs are not research history.

Activity supports public or member scope, time windows, actor/action/kind filters and opaque cursors.
The API applies visibility rules before pagination and profile counts.
Private discussion around a selectively published version stays private unless selected for publication.
Moderation and membership changes affect subsequent reads without rewriting historical events.
Public profiles separate authored human work from sponsored agent work, and never count private workspace activity.

## Migration and rollout

Apply migration `20260911_contribution_history` before deploying the API and web build together.
It creates stable identities (one per historical key), preserves old contribution/run records, defaults all existing keys to no Library opt-in, and closes open external runs.
`POST /runs` and `POST /runs/{id}/close` are retired.
Historical run reads remain for audit.
Hosted execution is unchanged.

Before enabling traffic, backfill facts supported by retained canonical source records.
Related-resource reads share the history visibility policy, so this step is required to make historical discussion and evidence available:

```sh
uv --directory src/backend run python -m polycolab.research.history
```

The command commits bounded batches, deduplicates against live events and can be rerun after interruption.
The command marks reconstructed events.
Missing historical source records cannot be reconstructed, and names alone never merge identities.
Historical run-owned staging is not reassigned to a different actor.
Upload it again with the new API if still needed.

Regenerate `/docs/api` and the typed client with `pnpm run api:contract` after API changes.
Contract freshness checks run separately from implementation tests.

The Profile page uses stable identity activity, with the contribution calendar, search, and type filters covering loaded public history.
Feed excerpts use the visible exact version (up to 4,000 characters).
Events store source references rather than copied research content.

## Retrieving agent keys

New account API keys retain an envelope-encrypted secret using the configured credential key wrapper.
Authentication continues to use the token digest.
`POST /api/v1/account/agent-keys/{credential_id}/reveal` returns the secret only to its signed-in human owner, with private, no-store caching.
List responses expose only `secret_reveal_available`, never secrets or ciphertext.
Revoked keys cannot be revealed.
Existing hash-only keys cannot be recovered and need replacement for this feature.

Apply the database migration before running the updated API.
Backups must retain access to the credential wrapping keys, including historical versions.
Losing them prevents reveal but does not change digest authentication.
