# Agent library

The `agents.library` service implements a library of prompts, single-file skills, and external plugin listings.
FastAPI owns authorization and persistence.
The standard Agents library remains available when hosted execution is disabled.
No worker, model provider, object storage or plugin installer is involved.

## Persistence and authorization

Stable entries identify their human owner, immutable type, optional exact source version, current draft revision, latest public version, and archive/moderation state.
Draft content lives separately from immutable published snapshots.
Versions retain their author identity/name, publication time, content and license.
Source-entry links are derived from the stored exact source version.
All public projections exclude draft content and owner-only revision/state fields.

Application entities and the capability-local store interface are independent of HTTP and SQL.
The SQL adapter participates in the shared transaction boundary and owns row locks and mutation receipts.
Publication locks the entry, checks the expected revision, and atomically creates a version and advances the entry.
Identical mutation retries reuse receipts; changed payloads conflict.
PostgreSQL and SQLite migrations protect published snapshots, moderation audits and entry identity with database triggers.
Archive and moderation operations advance the same revision guard as draft edits and publication.

Public lists use bounded, filter-bound keyset pagination, newest entry identity first.
Search reads published title, description and tags; Yours searches only the caller's draft content.
Public version history uses newest version identity first.

All mutations require an authenticated human.
An owner can edit, publish, archive or restore their own entries.
`AGENT_LIBRARY_MODERATOR_SUBJECTS` is an explicit subject allowlist, defaulting to empty; it grants library hiding/restoration only.
Moderator access does not expose private drafts.
Archived entries retain public version reads but leave discovery and prohibit new copies/updates.
Hidden entries deny all public reads and downloads; owner access and independent copies are retained.

## Content and API

`/api/v1/agent-library` exposes public discovery and human contribution routes.
`/yours` and `/{entry_id}/draft` expose private owner projections with no-store responses.
Entry versions, copy, publication, archive and moderation have separate endpoints.
Moderation state is readable only by configured moderators so hidden entries can be restored using the current revision.
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

Agents appears in desktop and mobile navigation at `/agents`.
Library, Yours and Connections share a shell; public entry and exact-version pages are under `/agents/library`.
The editor under `/agents/yours/{id}/edit` retains inputs on failures, guards unsaved navigation and requires a publication preview.
Public copying creates an independently editable private draft with exact source attribution.
The existing external-agent identity page is now `/agents/connections`.
Keys and model providers retain their Settings routes.
Public-content moderation includes an Agent library option and a current-revision loader.

This implementation provides copying/downloading and external-plugin discovery.
Custom-agent builders, bundled skill uploads, runtime activation, project-only sharing and improvement proposals remain future work.
