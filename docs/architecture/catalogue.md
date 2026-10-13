# Catalogue backend contract

Catalogue reads and mutations are standard product functionality without a deployment feature gate.
Authentication and human admission/moderation policy remain enforced.

## Admission and official history

Signed-in humans may immediately admit a statement with these fields:

- A nonblank title.
- A formulation.
- Explicit assumptions.
- A reported status.
- A reason.
- A literature source (identifier/version/locator) or an attributable human-review rationale.
  The service limits these fields and validates their structure.
  The service does not fetch sources, establish their validity, verify mathematics, or treat admission or reported status as endorsement.

An entry uses the research object's stable ID and selects one exact official revision.
`catalogue_revisions` stores immutable source/status metadata for each official revision.
`catalogue_audit` retains admission, promotion, edits, and moderation with actor, reason, revision, and contribution.
PostgreSQL enforces commons statement ownership, complete released official revisions, immutable history, exact-object FKs, and coherent human catalogue contributions.

Promotion admits an existing, currently released commons supporting statement without copying it or changing its original authorship.
It requires the current revision, explicit assumptions, and fresh admission source/status metadata.
Private or unreleased statements cannot be promoted.
The admitting human becomes the official editor.
The supporting statement's original author remains its research author.

Only the admitting human or an active moderator may revise official formulation or sourced status.
Edits require the current official base revision and append research/source history and an exact release atomically.
They do not overwrite unreconciled newer drafts.
Other actors receive 403 for official edits and may submit scoped correction suggestions.
Agents cannot admit, promote, edit official entries, moderate, or manage moderator assignments.

## Transactions and moderation

Admission, promotion, revision, and moderation require `Idempotency-Key` (1–200 characters).
Each receipt applies to one human and operation.
A versioned payload digest includes the destination and exact base.
Identical retries return the original entry/revision IDs.
Changed payloads conflict.
Replays recheck current authority.

Content, releases, source metadata, audit, provenance, receipt, and outbox commit together.
Failure rolls back the whole operation.

Mutations lock the retry key and then the commons scope.
Moderator assignments and revocation take the same scope lock, serializing authority changes with catalogue writes.
This coarse lock prioritizes correctness.
This contract makes no throughput claim.
Scoped research tools must preserve the same locking protocol.

Only authenticated human subjects explicitly listed in the deployment setting `CATALOGUE_OPERATOR_SUBJECTS` may grant/revoke moderator roles.
The setting uses verified authentication subjects, not email addresses or project roles.
Its default is empty.
Local account administrators are not implicitly moderators or catalogue operators.
Every assignment/revocation retains an immutable audit row and emits an outbox event.
Operators must grant themselves a moderator role if they also need moderation authority.

Only active moderators may hide/restore entries, with a required reason and exact official base.
Hiding removes entries from ordinary lists and public API responses.
Unknown and hidden entries return the same 404.
Only the admitting human or moderators can read private audits.
Hidden-entry audit access is moderator-only.
Retained audit and release rows are not deleted when content is hidden.

## HTTP and browser API

| Method | Path                                                  | Purpose                                 |
| ------ | ----------------------------------------------------- | --------------------------------------- |
| POST   | `/api/v1/catalogue`                                   | Admit a sourced statement               |
| POST   | `/api/v1/catalogue/promotions`                        | Promote a released supporting statement |
| POST   | `/api/v1/catalogue/{id}/versions`                     | Append an official formulation/status   |
| GET    | `/api/v1/catalogue/{id}/versions/{object_version_id}` | Exact released official version         |
| POST   | `/api/v1/catalogue/{id}/moderation`                   | Hide/restore with audited reason        |
| GET    | `/api/v1/catalogue/{id}/audit`                        | Authorized, bounded audit read          |
| PUT    | `/api/v1/catalogue-moderators/{user_id}`              | Operator-managed role assignment        |
| GET    | `/api/v1/catalogue`                                   | Anonymous keyset-paginated list         |
| GET    | `/api/v1/catalogue/{id}`                              | Anonymous exact official projection     |
| GET    | `/library/{id}`                                       | JavaScript application statement page   |

Version creation requires `expected_current_object_version_id` and a complete catalogue formulation.
Edited correction decisions use the same guard.
The old `/revisions` routes and `base_revision_id` field for these commands are not live aliases.
The service translates these requests into the historical stored format to preserve retry digests and existing correction proposals.
Promotion selects `object_version_id`, and moderation uses `expected_current_object_version_id`.
Neither accepts legacy field aliases.

Entry, exact-history, and list responses embed the shared typed `object_version`, with source and human-review metadata separate from its content.
The embedded version supplies its number and timestamp.
The old `statement` and `revision_number` response fields are removed.
Historical release JSON is not rewritten.
Audits identify `object_version_id`.
Correction decisions identify `suggestion_object_version_id` and `decided_object_version_id`.

Mutation responses contain `entry_id` and `object_version_id`, without a legacy `revision_id` alias.
Stored receipts and internal result decoding remain unchanged.
See the [live version contracts](research-versions.md#live-api-migration) for the shared cross-capability boundary.

JSON lists accept `limit` (1–100, default 25) and an opaque `cursor`, returning `items` and `next_cursor`.
Ordering is by stable UUID, not recency or interest.
The audit endpoint accepts `limit` (default 50) and an `after` audit UUID.
The following section describes Library search.
Community operations have separate API contracts.

Public DTOs select whitelisted fields from the immutable release, never an object's latest draft or project/session DTO.
They expose source/status and public author display names but no user, project, membership, conversation, run, credential, or contribution IDs.
All catalogue responses, including errors, use `Cache-Control: no-store`.
Shared research reads use the existing public-read rate limit.
HTML escapes research/source text and does not execute Markdown HTML, scripts, or external fetches.
Library pages render Markdown/LaTeX through the existing sanitized browser renderer.

The OpenAPI snapshot and generated client describe the JSON contract.
The Library uses the browser catalogue/reference adapters.
Existing Commons routes remain compatible.
Browser acceptance covers discovery, import, authentication return, and starting revision-pinned research with mocked APIs.
PostgreSQL coverage separately verifies the real migration and domain/API journey.

## Migration and verification

`20260906_catalogue` upgrades `20260905_baseline` incrementally and preserves existing research.
Run Alembic to `head`.
Do not reset a database on the supported baseline.
For incidents, use the [operator procedures](../../deploy/INCIDENTS.md).
Retain history rather than downgrading tables.

There is no catalogue feature switch.
Old pre-reset prototype revisions remain unsupported.

Focused tests live in `test_catalogue_api.py` and `test_catalogue_postgresql.py`.
The latter shares the disposable-schema fixture from `test_m0_postgresql.py`: set `M0_POSTGRES_TEST_URL` to an explicitly disposable PostgreSQL database.
Tests create/drop only random `m0_test_<uuid>` schemas.
They cover real API journeys, populated upgrades, history protection, concurrent retry/stale edits, and revocation against a waiting writer.
SQLite tests are supplementary evidence.

## Library search and imports

The [Library product decision](../requirements/library.md) extends this implementation with nullable literature metadata and server-attributed human-review rationale, reviewer and timestamp on immutable catalogue revisions.
Migration `20260910_library_review` preserves existing sources and free-form status values.

`GET /api/v1/library` searches only current, admitted, released, unhidden statements, filtering before pagination and ordering by revision creation time then revision ID descending.
It supports query, kind, status, source and basis.
Public catalogue history and exact-revision endpoints expose historical status basis while continuing to enforce current moderation.
`/library` is the primary UI.
Exact research links use `/commons/records/{revision_id}`.
Standalone public HTML links are removed.

Project-reference creation accepts explicit destination selection and optional new project creation with public/private visibility.
Creation defaults to public.
Reads include an available latest catalogue revision for explicit upgrades.
This behavior preserves existing references, history, write authorization, idempotency and exact research targets.
The Library does not call community interest/follow/summary services.
