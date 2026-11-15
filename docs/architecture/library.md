# Agent library

The `agents.library` service implements a library of prompts, single-file skills, and external plugin listings.
FastAPI owns authorization and persistence.
The standard Library remains available when hosted execution is disabled.
No worker, model provider, object storage or plugin installer is involved.

## Persistence and authorization

Stable items identify their human owner, immutable type, optional exact source version, current draft revision, latest public version, and archive/moderation state.
Draft content lives separately from immutable published snapshots.
Versions retain their author identity/name, publication time, content and license.
Source-item links are derived from the stored exact source version.
All public projections exclude draft content and owner-only revision/state fields.

Application entities and the capability-local store interface are independent of HTTP and SQL.
The SQL adapter participates in the shared transaction boundary and owns row locks and mutation receipts.
Publication locks the item, checks the expected revision, and atomically creates a version and advances the item.
Identical mutation retries reuse receipts; changed payloads conflict.
PostgreSQL and SQLite migrations protect published snapshots, moderation audits and item identity with database triggers.
Archive and moderation operations advance the same revision guard as draft edits and publication.

Public lists use bounded, filter-bound keyset pagination, newest item identity first.
Search reads published title, description and tags; My library searches only the caller's draft content.
Public version history uses newest version identity first.

All mutations require an authenticated human.
An owner can edit, publish, archive or restore their own items.
`LIBRARY_MODERATOR_SUBJECTS` is an explicit subject allowlist, defaulting to empty; it grants library hiding/restoration only.
Moderator access does not expose private drafts.
Archived items retain public version reads but leave discovery and prohibit new copies/updates.
Hidden items deny all public reads and downloads; owner access and independent copies are retained.

## Content and API

`/api/v1/library` exposes public discovery and human contribution routes.
`/mine` and `/{item_id}/draft` expose private owner projections with no-store responses.
Item versions, copy, publication, archive and moderation have separate endpoints.
Moderation state is readable only by configured moderators so hidden items can be restored using the current revision.
Every write requires an Idempotency-Key.
Draft updates, publication, archive and moderation require expected_revision.

Prompts contain plain text with no template evaluation.
Skills contain a single UTF-8 SKILL.md with required name and description YAML frontmatter.
Safe YAML parsing rejects aliases and anchors and bounds frontmatter size.
Supporting files remain external references.
Downloads preserve the exact stored text, use a fixed attachment filename and disable MIME sniffing.
Plugins contain source/setup metadata rather than executable packages or a Polycolab manifest.
HTTP(S) source URLs prohibit embedded credentials and control characters and are never fetched by the server.

## Browser

Library appears in desktop and mobile navigation at `/library`.
Library and My library share a shell; public item and exact-version pages are under `/library/items`.
The editor under `/library/mine/{id}/edit` retains inputs on failures, guards unsaved navigation and requires a publication preview.
Public copying creates an independently editable private draft with exact source attribution.
Retired `/agents` routes return not found; API key settings live at `/settings/api-keys`.
Keys and provider connections retain their Settings routes.
Operator moderation remains available through the library API with current-revision checks.

This implementation provides copying/downloading and external-plugin discovery.
Custom-agent builders, bundled skill uploads, runtime activation, project-only sharing and improvement proposals remain future work.
