# API contract and reference

FastAPI is the only producer of Polycolab's machine-readable API contract.
The checked-in [OpenAPI snapshot](../../src/web/openapi.json) and the generated TypeScript output in `src/web/src/lib/api-client/generated` are derived artifacts.
Do not edit them by hand.

Run `pnpm run api:contract` after an intentional API change.
CI runs `pnpm run api:contract:check`, which fails if either the snapshot or generated client is stale.
Browser code imports the frontend API client module through `$lib/api-client`.
Its callable `createApiClient` factory uses types from the generated `paths` map.

The [external-agent API guide](external-agent-api.md) summarizes delegated HTTPS operations.

## API conventions

- Mutation request schemas reject unknown fields with 422, including caller-supplied actor/authority fields.
  New projects default to public.
  Callers can explicitly create private projects.
  Owners can change visibility.
  Creation and reads enforce the current visibility and access policy.

- Operations use versioned paths below `/api/v1` and have stable operation IDs.
- Human operations use `BearerAuth`.
  External agents use a distinct opaque bearer key on shared `/api/v1` research resources.
  It is never a human session or worker secret.
  The same resources provide safe anonymous public projections.
- Errors use `ErrorEnvelope`: `{"error":{"code":"...","request_id":"..."}}`.
- Every list operation accepts `limit` (1–100) and an opaque `cursor`.
  It returns an array plus `X-Total-Count` and, when another page exists, `X-Next-Cursor`.
  Clients must treat cursors as opaque and use the documented deterministic order.

## Built-in social-auth browser contract

These `/auth` routes are a browser adapter and are intentionally excluded from the public OpenAPI/client contract.
They exist only with `AUTH_MODE=local` and a fully configured provider.
`GET /auth/config` returns `social_providers` as an ordered subset of `google` and `github`.
It never returns client IDs, secrets, tokens, subjects or flow state.

`POST /auth/social/{provider}/start` accepts `{"return_path":"/fixed-local-path"}`.
The linking form is `POST /auth/social/{provider}/link/start`.
Both require an exact `Origin` equal to `PUBLIC_APP_ORIGIN`, reject external/query/fragment return targets, and return the provider name, fixed provider authorization URL and expiry.
The server also sets a short-lived `HttpOnly`, `SameSite=Lax` browser-binding cookie scoped to `/auth/social`.
It is `Secure` except for explicitly local loopback HTTP.

The provider callback is `GET /auth/social/{provider}/callback`.
Before any token, JWKS or user request, FastAPI atomically consumes the state row while checking its provider, expiry and browser binding.
It then closes that transaction for external I/O.
Success creates or resolves the immutable `(provider, subject)` mapping, issues the normal local session cookie, clears the flow cookie and redirects with `social_auth=success`.
Denial, replay, mismatch, expiry, provider failure and link conflict issue no new session and redirect with `social_auth=failed`.
Both outcomes use a previously validated local return path plus `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.

Arbitrary callback/return URLs are never accepted.

`POST /auth/reauthenticate` refreshes recent-authentication state using the existing password and exact Origin.
Authenticated clients may read configured/linked methods at `GET /auth/social/identities`, start an explicit link flow, and call `POST /auth/social/{provider}/unlink` with the exact Origin.
Link completion rechecks the originally bound, unrevoked, recently reauthenticated session after provider I/O.
Unlinking fails when it would remove the account's last password or active social identity.
Frontend code must clear prior private UI state when a successful callback changes accounts.

## Built-in registration browser contract

These browser-only routes exist only with `AUTH_MODE=local`.
`GET /auth/config` returns `registration_mode` as `closed`, `open` or `invitation` only in local-auth mode.
`closed` is the default.
OIDC configuration never advertises local registration.
After migrations, the deployment bootstrap command creates the fixed `admin` account from `BOOTSTRAP_ADMIN_PASSWORD` only when the account registry is empty.
There is no browser administrator-setup endpoint.

Repeated bootstrap runs never change existing accounts or passwords.
Ordinary registration fails with `setup_required` until an administrator exists.

`POST /auth/register` accepts exactly `username`, `password`, optional `display_name`, and optional `invitation_code`.
The contract excludes email, terms acceptance, administrator flags, account IDs and membership requests.
The API rejects these as unknown fields.

Usernames use the existing normalized 3–80 character policy.
Passwords use the existing 12–256 character policy.
Display names are at most 200 characters.
Open mode rejects an invitation code.

Invitation mode requires a valid code.
Closed mode returns `registration_closed`.

Registration requires an exact `Origin` equal to `PUBLIC_APP_ORIGIN`.
Before password hashing, the API consumes a durable per-minute admission bucket keyed by a deployment-HMAC of the client address.
The API honors forwarded addresses only from configured trusted proxy networks.

`REGISTRATION_MAX_REQUEST_BYTES` limits the complete request.
An outer ASGI middleware limits actual chunks before the application buffers them.
This limit also applies to bodies without a trustworthy declared length.
The middleware replays accepted bodies into the normal admission/registration policy.
It is not a transport timeout or aggregate connection limit.

Those remain ingress responsibilities.
Successful registration atomically creates one non-admin account and one opaque session, optionally consumes one invitation, and sets the normal Secure/HttpOnly/SameSite cookie.
Failure creates neither a partial account nor session.
Responses are `no-store` and never echo passwords or codes.

Password login consumes durable per-minute address and normalized-username buckets before scrypt verification.
Both keys are deployment-HMAC identifiers.
Raw addresses and usernames are not retained in admission rows.
Unknown, invalid, and existing usernames all perform one scrypt verification and invalid credentials share the same response.
Either admission bucket returns `login_rate_limited` with `Retry-After`.
Ingress remains responsible for aggregate connection and timeout limits.

In invitation mode an authenticated built-in administrator may issue a code with `POST /auth/registration/invitations {}`, list at most 100 records with `GET /auth/registration/invitations`, and revoke one using `DELETE /auth/registration/invitations/{id}`.
Issuance returns the opaque code exactly once for operator-mediated delivery.
Storage retains only its SHA-256 digest.
Lists expose status and timestamps but no code.
Codes have the configured bounded lifetime and concurrent consumption is single-use.
Invalid, expired, revoked and replayed codes share `invalid_registration_invitation` and cannot create an account.

The stable registration errors are `registration_closed` (403), `setup_required` (409), `registration_conflict` (409), `invalid_registration_invitation` (400), `registration_request_invalid` or `validation_error` (422), `registration_request_too_large` (413), and `registration_rate_limited` (429 with `Retry-After`).
Dependency failures use the normal content-free internal error.

### Project membership

`POST /api/v1/projects/{project_id}/members` accepts `role` and exactly one of the existing canonical `user_id` or an exact built-in `username`.
Username input uses the same trim, case-fold and syntax normalization as registration, then performs one server-side equality lookup against the unique built-in-account index.
An unknown or invalid username returns the same `invalid_member` response.
There is no account search, suggestion or public-directory endpoint.
The existing owner authorization, duplicate-membership conflict and last-owner mutation rules remain authoritative.

Membership create, list and update responses include canonical `user_id`, nullable `username`, nullable `display_name`, role and creation time.
Built-in accounts use their normalized username and account display name.
Provider-neutral users added through the preserved `user_id` boundary may have no built-in username.
An owner may add a built-in account before its first API read.
Exact username resolution creates its canonical application user in the same transaction as membership creation.

### Optional verified email and password recovery

Recovery UI follows configured mail capability.
The repository retains queueing and token APIs.
An operational mail delivery integration is required.

Built-in accounts may inspect and change recovery state through `GET/PUT /api/v1/account/email`.
Changes require the current browser session to have recent password authentication.
`POST /api/v1/account/email/resend` rotates the pending verification capability.
The existing verified address remains effective while a replacement is pending.
`POST /api/v1/account/email/verify` consumes a 24-hour single-use token and atomically promotes the exact pending normalized address.
Verified normalized addresses are globally unique.

`POST /api/v1/auth/password-reset/request` always returns the same accepted shape for syntactically valid known and unknown addresses.
Only an exact currently verified address can enqueue mail.
`POST /api/v1/auth/password-reset/confirm` consumes a 30-minute single-use token, changes the password, invalidates every remaining reset token and revokes all existing sessions in one transaction.
Requests use durable HMAC-scoped hourly admission counters.
All recovery responses are `no-store`.
State-changing requests require the configured exact browser origin.

Raw verification/reset tokens are never persisted.
Their digests bind canonical token rows.
The API stores the recipient and token-bearing action URL only in an envelope-encrypted `mail_outbox` payload.
Encryption uses the configured KMS/key wrapper and row-specific authenticated context.
Plaintext queue metadata is limited to account/token identity, fixed purpose, lifecycle, expiry, attempts and claim fencing.

Bounded `SKIP LOCKED` claims provide at-least-once delivery: a crash after SMTP acceptance but before acknowledgment can duplicate mail.
Stale claim generations cannot acknowledge a new lease.

Delivery, cancellation, expiry and terminal failure erase ciphertext and wrapped keys.
Retries retain them only until the token expiry and maximum attempt bound.

### Project visibility and external agents

Public and private projects share one API.
Creation defaults to public.
Owners can change visibility.
Public research uses safe projections and never exposes memberships, credentials, private notes or conversations.
See the [application configuration contract](application-configuration.md) for capability settings, browser behavior and the public configuration endpoint.

Public project moderation uses `PUBLIC_PROJECT_MODERATOR_SUBJECTS` independently of catalogue moderation.
It retains exact-version checks, idempotency and audit.
Account-wide external-agent keys use the [shared research API](external-agent-api.md) and follow live sponsor memberships, including private projects.

## Schema foundations

The `20260905_baseline` migration creates project/commons ownership, immutable typed revisions, exact-release storage, general provenance, mutation receipts, and an outbox.
Later migrations extend these foundations for direct writes, selective publication, artifacts, and job lifecycle.
Production language runners remain unfinished.
The [catalogue endpoints](catalogue.md) support admission and public reads.
Reads and mutations are now standard features, subject to their access and human-authority policies.
Version-1 agents retain their limited tool contract.

Scoped direct-write operations use version-2 grants.

### Research and reference API

The [object/version contract](research-versions.md) defines the current live snapshot and relationship shapes.
Database names and frozen historical payloads retain their original encodings.
These are not accepted legacy write aliases.
`POST /api/v1/records` is removed.
Record creation uses complete `/objects` commands.
Dedicated note and summary histories retain independent revision fields.

Records, public record reads, scoped relations, and project references have no deployment feature gate.
Typed records support exact statement attachments, retained failure explanations, immutable revisions, author/moderator edit policy, and required `Idempotency-Key` headers.
Record pages return `{items, next_cursor}`.
Bounded relation lists use `X-Next-Cursor`.
Public reads omit private incoming relations and disappear when their catalogue ancestry is hidden.
These responses, including errors, use `no-store`.

`POST /api/v1/project-references` pins an exact `object_version_id` without copying a public statement.
New projects default to public.
The Work privately action explicitly selects private visibility.
`POST /{reference_id}/versions` under that prefix requires `expected_current_reference_version_id`.
GET lists current pins or a reference's history.

Hidden sources retain their internal attribution.
The API returns no source title or content for an unavailable pin.

Reference events remain private.

`POST /api/v1/project-copies` instead creates an independent editable object from the frozen Library projection selected by `source_object_version_id`.
It returns `project_id`, `object_id`, `object_version_id`, and `source_object_version_id`.
The initial snapshot retains an exact attachment to its source.
Neither later Library edits nor project edits change the other object.
Existing copy retry receipts retain their original internal encoding.

Runs may explicitly pin accessible public inputs.
Cached manifest and tool reads recheck access.
Requested write authority is a separate, versioned optional turn field governed by explicit per-run authorization, not a feature flag.
Version-1 agents reject it.
Explicit version-2 sessions expose grant-filtered `write_object_version` and `create_relation` tools, committing exact output scope and trusted invocation provenance with content.
Public-task grants exclude the private session transcript and cannot include private research inputs.

Direct-write authority must be explicitly requested and granted for each run.

Public correction suggestions are `NOTE` records with a typed `suggestion` formulation attached to its exact catalogue base.
They may be authored by humans or public-context agents using the record tool.
Human catalogue editors decide them through `POST /api/v1/records/{object_version_id}/decision`: accept, edit-and-accept, or reject.
Accepted catalogue revision and decision commit atomically.
Submitted text remains immutable.
Private proposals cannot use this path.

Decision reads omit internal user identifiers and recheck the suggestion's public availability.

Typed statements and records retain explicit assumptions, reported outcomes, and explanations.
Live writes use complete snapshots through `POST /api/v1/objects` and `POST /api/v1/objects/{object_id}/versions`, with an explicit `expected_current_object_version_id` for an append.
Metadata and structural pins must be supplied.
Omitted fields do not inherit.
Historical stored proposals keep their original interpretation, but new proposals and human-edited commands use the complete snapshot contract.
Neither path copies independent assurance.

The service rechecks attachment availability under the commons lock before committing.
Unavailable targets reject the edit without losing its existing history.
Private revision edits require the object's author as well as current project write access, matching the typed-record endpoint.
Use the typed editor to deliberately change assumptions, outcomes, or explanations.

Public record history with an explicit `object_id` includes accessible official catalogue revisions as well as attached research revisions.
The unfiltered public record feed remains limited to attached research.
Catalogue discovery has its own endpoint.
History never bypasses current release/moderation filters.
Scoped relation lists expose `X-Next-Cursor` to the browser, including across the allowed development origin.
Relationship writes always specify exact endpoints.

Record DTOs expose optional `catalogue_entry_id`, `catalogue_source`, and `catalogue_reported_status` only when that exact revision has catalogue metadata.
Historical JSON and no-JavaScript HTML use that revision's source, never the current official revision's citation.
The exact-record browser page lists research attached to that statement revision using bounded pages and links separately to the current official statement.
Official revisions do not offer generic record editing or duplicate catalogue promotion controls.

`GET /api/v1/discovery` searches public research and catalogue sources.
`GET /api/v1/discovery?project_id=...` searches only the authorized project.
Both return `{items, next_cursor}` with SQL-applied filters and limits.
PostgreSQL uses the `simple` full-text configuration.
SQLite tests use substring matching.
Public discovery and authenticated member-project discovery are always available.

Scope and membership checks prevent private records from leaking into public results.
`PUT /api/v1/community/{entry_id}/follow` and `/interest` independently set a human's intent with `{active: boolean}`.
GET on the community resource returns the caller's state.
`/api/v1/community/{entry_id}` exposes only aggregate interest.
These actions do not modify research status or assurance.

Assigned human moderators can hide/restore a public contribution through `POST /api/v1/records/objects/{object_id}/moderation`, supplying an exact current base, reason, and retry key.
GET on that route returns bounded audit history to moderators.
All revisions of the hidden object leave public reads and discovery.
Editing and promotion require restoration first.
Catalogue entries continue to use their separate admission/moderation policy and endpoints.

`GET /api/v1/notifications` returns only the signed-in user's currently accessible research updates.
`GET /api/v1/community/{entry_id}/summary` returns a pending or ready bounded source-linked snapshot with reported-status counts for both records and supporting statements, not assurance.
The service reads summary items and their typed outcomes together, without a metadata query per item.
The application-owned community consumer processes canonical outbox events in bounded transactions with resumable recipient cursors.
Notification delivery is idempotent.
Cached summaries and notifications recheck moderation and reference access before returning data.

Shared research supports public and member project projections according to live access.
Replaced `/api/v1/projects/...` routes are removed.
Browser project URLs are unchanged.
Research tables retain their project identity along with ownership scopes and immutable revisions.
Reviewed proposal acceptance writes one agent contribution envelope with typed output FKs in its research transaction.
Direct human research also creates contribution/output/outbox rows.

The composable `record_contribution` service additionally supplies durable retry receipts and a callback receiving the envelope before creating content.

Supported databases upgrade incrementally from the baseline to `head`.
Pre-reset prototype revisions are unsupported.
See the [schema contract](research-schema.md).

### Research structure

Complete object snapshots represent independently addressable alternative proofs as canonical `PROOF` objects with typed `content` and `structural_relationships`.
Each version pins one exact conclusion and an ordered joint premise list.
Its content records reported progress.
Historical storage encodings remain readable.
See [object kinds](object-kinds-and-reviews.md) for the canonical API vocabulary and its internal compatibility mapping.

Ordinary relation requests accept `IMPLIES` and `EQUIVALENT_TO` in addition to the existing relation vocabulary.
These exact revision-pinned associations may be reciprocal or cyclic.
They are descriptive research links, not proof-premise edges, and cannot satisfy or bypass the separately checked acyclic proof dependency graph.

An `ATTEMPT` snapshot carries typed content and structural pins targeting an exact version of any non-attempt research object.
It can pin exact input, supporting, contradicting, and output evidence and may identify only a newer revision of the same target as its result.
Attempts are distinct from edits and controller job retries.
`GET /api/v1/research/objects/{object_id}/attempts` returns a bounded, permission-filtered history and can filter by exact target revision.
The public counterpart returns only attempts whose target and dependencies are currently available through explicit releases.

Each research object can have one human-owned private note stream and one canonical authored-summary stream.
Their `PUT` routes require an exact base revision after creation, preserve immutable history, and use an `Idempotency-Key`.
Agents cannot write human notes.
Authored summary revisions pin all source revisions.
Their `fresh` marker reports whether every source is the latest revision visible in the requested scope, without exposing inaccessible revision activity.
They are separate from rebuildable community summaries.

Human-note reads include the owning user ID and an authoritative `can_edit` capability for the current human actor, so clients do not infer ownership policy.
Append-only comment and progress routes always pin an exact object revision.
All associated-resource history routes use bounded opaque cursors, recheck the requested project scope, and preserve actor attribution.

Authenticated clients resolve exact target and dependency labels in one bounded request through `POST /api/v1/research/versions/display`.
The request accepts at most 128 unique `object_version_ids` and preserves their input order.
It returns only the object-version ID, object ID, kind and title.
It fails as not found if the caller cannot read the requested project or any requested revision.
This avoids per-revision browser requests without weakening exact-revision authorization.

Version-2 direct-contribution grants can expose `write_summary`, `comment_on_object_version`, and `report_progress` when their corresponding authority operations were requested.
The dispatcher validates every target and summary source against the pinned public manifest or same-run outputs.
It uses the same lease fence, retry receipt, budget, and provenance transaction as other scoped writes.
No `write_human_note` tool exists.

Endorsement and correspondence records remain append-only, human-authored assurance about exact revisions.
They do not change a sketch or attempt's reported progress, proof state, catalogue state, or future machine-observation state.
Artifact and job bindings do not establish production machine assurance.

`GET /api/v1/assurance/{object_version_id}/current` returns bounded current positions with a stable `assessor_id`: one latest endorsement per assessor and one latest correspondence position per assessor and exact statement revision.
Latest means greatest `(created_at, id)`, not greatest UUID.

The existing exact-revision assurance GETs are chronological append-only history.
`limit` applies across both event kinds and `next_cursor` is one opaque temporal cursor.
The former raw `after` UUID parameter cannot express chronological pagination.
The API deprecates and rejects this parameter.
Public and scoped variants retain their existing exact-revision and correspondence-target authorization.

`FORMALIZATION` and historical `COMPUTATION` records support authored research and exact artifact attachments.
Historical computations project as canonical Notes while retaining source semantics.
Reported outcomes remain self-reported activity.
A trusted verification result is required for machine assurance.

### Selective publication

Only a human project owner can call `POST /api/v1/publication/preview`.
It accepts exact selected revisions and optional authored-summary revisions, comments, progress updates, and relations.
The response computes a bounded required revision closure, including record attachments, proof-sketch conclusions/premises, attempt targets/evidence/results, summary sources, comment and progress targets, and selected relation endpoints.
Its digest binds the original selection, required closure, and complete sanitized public fields.

`POST /api/v1/publication/confirm` requires the same exact selection, preview digest, reason, and `Idempotency-Key`.
It locks and reauthorizes the publisher, recomputes the preview, and atomically stores the immutable manifest, typed members, exact releases, contribution provenance, and retry receipt.
A changed payload, already-confirmed digest, inaccessible dependency, lost ownership, or mismatched preview fails without partial releases.

`GET /api/v1/publication/history` returns bounded owner-visible manifest history.
`GET /api/v1/publications/{manifest_id}` returns the exact anonymous manifest without its private project identifier.
Public exact-record reads use the immutable released field snapshot after rechecking current moderation and dependency access.
Later private revisions are not released implicitly, and the publication does not admit statements to the catalogue.
Dedicated human notes, private conversations, internal events, and unselected associated activity have no public manifest field.

Authenticated project members use `/api/v1/projects/{project_id}/artifacts` to stage bounded binary uploads, read safe metadata, commit an exact research attachment and download verified committed bytes.
Upload declarations bind lowercase SHA-256, length, media type and an optional source revision.
The service rechecks current project authority around storage I/O.
It never exposes storage keys or raw filenames.
It serves untrusted content only as generic downloads with restrictive headers.

The application GC claims expired, uncommitted staging bytes.
Committed bytes are never swept.

The implemented reload-discovery contract exposes a bounded private `GET` on that collection.
It returns one committed artifact-attachment row per item, ordered by attachment UUID.
It uses `{items, next_cursor}` keyset pagination with a `limit` from 1 to 100 (default 25).
An optional exact `object_version_id` filter applies before pagination.

Each item contains safe artifact integrity metadata, attachment ID, optional source revision, exact attached revision, optional high-level attempt, role and attachment timestamp.
It returns no total, storage location, raw filename or bytes.
Staging and deletion states remain absent.
Project and optional revision authorization occur before the scope-filtered query, and downloads are separately reauthorized.

Publication selection now accepts up to 32 exact `artifact_ids`.
Preview requires each artifact to be committed in the selected project.
It snapshots all current exact research bindings for each artifact.
It adds those bindings and the optional source revision to the required revision closure.
It verifies the stored bytes before returning.

The digest binds the ordered artifact selection, sanitized SHA-256/length/media, optional exact source, safe actor attribution, exact links and stable anonymous content path.
Confirmation rechecks the same bytes before the existing locked preview/manifest/release transaction and inserts typed artifact membership only after the required exact releases exist.
Missing, corrupt, inaccessible, uncommitted or newly rebound artifacts fail without partial publication.

`GET /api/v1/artifacts/{artifact_id}` and its `/content` child resolve artifacts selected by a still-readable publication manifest or committed and attached to currently readable public-project research.
The service verifies anonymous content on every storage read.
It serves this content as `application/octet-stream` with download, nosniff, sandbox and no-store headers.
It rechecks moderation after retrieval.
Uncommitted, unattached, hidden-project and later private bindings remain private.

The verification service registers authenticated human submission, inspection, event replay, cancellation and exact-manifest rerun under `/api/v1/projects/{project_id}/verification-jobs`.
Its generated contract exposes those human operations.
Authenticated members may discover only currently available curated versions through the UUID-cursor-paginated `/api/v1/projects/{project_id}/verification-environments`.
The response contains exact image/toolchain/dependency/build/platform identity and finite supported ceilings, never credentials or runner configuration.
Discovery remains available while submission is disabled and does not imply execution readiness.
OpenAPI excludes the separate `/internal/verification` controller boundary, which requires a deployment-managed credential.

Claim also requires the separate execution flag.
Submission and execution remain independently disabled by default.
The service owns atomic admission and quotas, finite reservations, fenced controller-attempt generations, leases and recovery, append-only events/results, exact input retrieval and verified staged-output binding.
It provides no sandbox, compiler or process launcher, and registering the routes does not execute submitted source.

The service interprets every `SOURCE` revision as exact UTF-8 `content_md`.
`LEAN_CHECK` requires a `FORMALIZATION` source.
Python purposes require `COMPUTATION`.
Other input roles may use authorized exact revisions or committed artifacts.
Agent artifact inputs require explicit human selection in the immutable run manifest.
Matching hashes, neighboring artifacts and unlisted same-scope IDs remain denied.

`COMPLETED` and retained controller results are observations, not mathematical assurance.
Assurance requires a separate exact verification binding.

## Private Runtime API

Both in-process and API-backed execution use the same model-message selector.
Public direct grants include only immutable agent instructions and the separately declared public task, never the private session transcript.
The API-backed worker forwards trusted source-event cursors for `write_object_version`, `create_relation`, and `submit_proposal`.
The tool boundary validates these against the canonical run event before accepting a mutation.

Version-2 `get_context` and `get_object_version` results include a whitelisted `research` block with kind, assumptions, reported outcome/explanation, safe authorship, and exact catalogue source/status.

A queued private turn may also name up to 32 committed artifact IDs.
The immutable manifest stores typed artifact FKs and binds them into its digest.
Each use rechecks current project access.
`get_context` returns only ID, digest, byte length and media type.
Byte retrieval remains controller/API-owned.

The service adds a completed verification output to the originating agent run through a separate immutable typed artifact/result binding.
It may be used by a later job in that same run but never mutates the input manifest or authorizes another run.

Live tools return the version contract while stored manifests retain their historical encoding.
The API returns these fields only after the pinned-input or same-run-output access checks.
The metadata does not add neighboring revision IDs, credentials, storage keys, filenames, or private run identifiers to the response.

The worker-only `/internal/v1/runtime` boundary is deliberately absent from the public OpenAPI document.
A deployment-managed bearer credential authenticates the worker, while run IDs, lease generations, idempotency keys, and server-side authorization constrain every state mutation.

The API accepts a current worker credential and, during a bounded rotation window, one explicitly expiring previous credential.
The API emits authentication outcomes as content-free security audit events and bounded metrics.
Request and response byte ceilings apply independently.
An oversized claim envelope fails the claimed run.
The API does not send the envelope to the worker.

The boundary owns claims and immutable execution envelopes, lease renewal, one-use model-grant issuance, normalized event and usage commits, and terminal transitions.
Workers have no PostgreSQL credential.
The Tool Gateway and Model Gateway remain separate run-scoped private interfaces within the same FastAPI deployment.

## Private hosted-tool API

The implemented private route is `/internal/v1/tools/call`.
It is absent from the public OpenAPI contract and browser network surface.
The dispatcher lives in `src/backend/polycolab/agents/tools.py` and uses platform-owned function schemas over HTTP.
The browser never calls the worker, and the gateway authorizes each tool call before invoking shared domain services.

```text
Hosted worker -> private run capability -> Tool Gateway -> domain services
```

The base allowlist is `get_context`, `get_object_version`, `get_dependencies`, and `submit_proposal`.
Version-2 runs with explicit contribution authority can also receive grant-filtered `write_object_version`, `create_relation`, `write_summary`, `comment_on_object_version`, and `report_progress` tools.
Reads return only inputs from the manifest and outputs from the same run.
Scoped direct contributions require no deployment flag.
An independent human-approved `RUN_VERIFICATION` project grant may add `submit_verification`, `inspect_verification` and `cancel_verification` while the submission flag is enabled.
Record/relation edit grants never imply computation authority.

Verification mutations validate the canonical `TOOL_REQUESTED` event cursor and retain run/session/context provenance.
Explicit typed manifest artifacts may be verification inputs, but general artifact byte tools and implicit same-scope artifact access remain unavailable.
The hosted dispatcher is not a standards-conformant MCP server.

## Non-execution operational telemetry foundation

The existing `/internal/v1/metrics` route remains disabled by default and limited to explicitly configured operator subjects.
`operational_telemetry.py` now owns typed, content-free primitives for the agreed community-outbox and database-pool series, but the route and engine/consumer lifecycle do not call them yet.

The community snapshot counts events without a completed `community_delivery_cursors` row and computes the oldest such event age without selecting payloads or identifiers.
PostgreSQL applies a transaction-local finite statement timeout.
Migration `20260908_0021` adds the leading `(created_at, id)` index concurrently.
The current claim index has a different leading column and cannot establish this access path.
Publishing uses only the fixed `community` consumer label and removes both gauges on snapshot failure before recording the bounded success/error counter.

Pool primitives accept only the code-owned `api` and `community` roles and the `acquired`/`timeout` outcomes.
They expose configuration, checked-out connections and checkout duration without accepting deployment names or private identifiers.
Application infrastructure owns lifecycle hooks and protected-route integration.
These metrics add no allocator, execution metric, public API/OpenAPI field, or browser operations contract.

## Scalar policy

`/docs/api/` serves the Zensical API page and mounts Scalar directly into that document using `/api/openapi.json`.
It does not use an iframe.
Its static loader also works against Vite's checked-in OpenAPI snapshot without a running API.
The backend route enforces the reference access policy in production.
Without a web build, `/docs/api/` falls back to the standalone reference.
The configuration disables persistence of authorization, the embedded client/test controls, developer tools, telemetry, proxying, MCP/agent access, and plugin URLs.

The read-only layout maps Scalar's native variables onto Polycolab's shared EPFL and accessible-extension color tokens.
It renders curated guidance from the canonical OpenAPI description.
The guidance covers quick start, authentication, pagination, errors and immutable IDs.
Representative public discovery, public exact-read, private project and scoped agent-session operations carry curated summaries and examples.
This documentation adds no API capability.
The browser asset is an exact `@scalar/api-reference@1.62.6` CDN URL protected by a SHA-384 subresource-integrity hash.

Local and staging environments enable the reference without authentication.
Production defaults to disabled.

For a public read-only reference, set `API_REFERENCE_ACCESS=public`.
For restricted access, set it to `operators`.
Also configure `API_REFERENCE_OPERATOR_SUBJECTS` as a JSON array of OIDC subjects for restricted access.
`disabled`, `public`, and `operators` are the only modes.

For compatibility, the legacy `API_REFERENCE_ENABLED=true` retains its former operator-only production meaning and still requires the allowlist.
The OpenAPI JSON remains the stable machine contract in every mode.

## Reference navigation

The introduction covers authentication, permissions, pagination, errors, budgets and retries.
The sidebar groups operations into these sections:

- Identity and API keys.
- Projects.
- Shared research.
- Artifacts.
- External runs.
- Library/publication.
- Research context and assessment.
- Community/accounts.
- Optional hosted services.
- Operator administration.

`app/reference.py` maps each operation ID to exactly one presentation tag.
OpenAPI `x-tagGroups` and tag metadata include only sections with operations.
Contract tests reject unclassified operations, duplicate placement and empty sections.
Operation descriptions identify access and optional hosted-service availability.
Agent-write descriptions identify run and idempotency headers.
External agent runs and human key management are separate from optional hosted sessions and runs.

Catalogue audit reads remain with Library operations rather than operator actions.
This organization preserves paths, operation IDs, request schemas and authorization policy.
Scalar's developer toolbar is hidden and no tag opens automatically.

The embedded API reference follows Zensical's selected light or dark mode.
Zensical remains the only visible theme control and Scalar remounts when that mode changes.
The standalone fallback remains light and uses the equivalent Canard mapping.
Scalar's independent theme toggle and attribution are hidden alongside the developer toolbar.
