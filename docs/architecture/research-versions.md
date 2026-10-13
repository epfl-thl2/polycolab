# Research object and version foundation

The implementation includes application snapshot classes, canonical relationship storage, and complete history content.
Exact, history, embedded, and scoped record reads share a kind-discriminated version response.
Live cross-capability API contracts and browser/agent consumers use explicit object-version references.
See the [object kinds and reviews contract](object-kinds-and-reviews.md) for current creation kinds.

## Application snapshots

`src/backend/polycolab/entities/research.py` defines frozen `ResearchObject` and `ResearchObjectVersion` parents, with concrete object and version classes for the supported kinds.
The registry connects persisted encodings to these classes and creation support.
Current creation uses the [canonical kinds](object-kinds-and-reviews.md).
Historical proof and attempt rows remain readable.
Missing structured conclusions, targets, progress, or findings are not fabricated.
New writes require complete structure under the current kind contract.

A stable object holds its ID, kind, ownership scope, creation authorship/time, and `current_object_version_id`.
Loading it does not load version content.
`ResearchObjectRead` explicitly pairs an identity with a selected exact version.
The selection can differ from the actual head, and neither raw entity is a safe anonymous response.

A version contains `id`, `object_id`, `kind`, `number`, `previous_object_version_id`, `schema_version`, typed immutable `content`, optional `change_summary`, `authorship`, `created_at`, and a tuple of `structural_relationships`.
Content includes title/body and common metadata.
Proof content adds reported progress, and attempt content adds outcome/findings.
The predecessor is the immediately previous version, not the first version.

`ObjectVersionRelationship` has ID, type, binding, ownership scope, authorship, timestamp, and optional description.
`UnidirectionalRelationship` has `source_object_version_id` and `target_object_version_id`, with positions for premises/evidence and an evidence role where applicable.
`BidirectionalRelationship` has `first_object_version_id` and `second_object_version_id`, canonicalized by UUID.
Neither endpoint owns or endorses the relationship.
Currently only `EQUIVALENT_TO` is bidirectional.

Binding is independent of direction: structural relationships are frozen with their source version.
Declarations can be added independently between existing versions.
Distinct roles and separately authored declarations remain distinct.
Typed attachment, premise, conclusion, target, evidence, and result accessors derive from canonical relationship values, rather than parallel attribute lists.
This relationship model adds no assertion/assessment entity.

Snapshot reads use the capability-local repository protocol and a SQL adapter that batches content, structures, attachments, and attribution.
The `ResearchSnapshots` application reader materializes caller-selected identities.
Callers must authorize those identities before reading.
Raw application snapshots are not public projections and must not be serialized anonymously.
Existing mutation services retain authorization, locking, idempotency, and transaction ownership and now use the shared kind registry for classification.

## Storage and public history

The existing `research_objects`, `object_revisions`, and typed content tables remain authoritative for identities and content.
`object_version_relationships` is the sole relationship store.
Every version stores a complete snapshot, not a patch.
A new version inserts its complete structural sets and advances the object pointer atomically after an exact-base check.
Existing PostgreSQL constraints protect the linear chain, immutable content, endpoint shapes, structural roles/cardinality, ordered positions, and contribution scope.

Migration `20260914_version_relationships` preserves declaration IDs and their publication/contribution links, copies structural rows, merges duplicate attachment representations, and removes redundant structural columns/tables.
Proof/attempt tables retain non-relationship content.
Legacy ORM names are read projections over canonical rows, not alternate write stores.
A read-only `relation_assertions` compatibility view supports the existing output-scope trigger.
Frozen release JSON, digests, and historical attribution are unchanged.

The migration is forward-only.
Create a backup before deployment.

Rollback requires restoring the database and matching application build, not discarding history.
Verification-job coherence resolves attempt targets from canonical `TARGET` relationships, not removed attempt-table columns.
Reviewed snapshot and declaration writes derive provenance from the contribution envelope so human review preserves `AGENT_PROPOSAL` attribution.

PostgreSQL 18.3 tests cover these paths alongside artifact bindings, scheduling constraints, populated relationship upgrades, and baseline schema/integrity checks.
The broader local PostgreSQL 18.3 audit passes all 95 tests selected by `pytest ../../tests/backend -k 'postgresql or scheduling_foundation'`.
These tests cover publication, catalogue, records, proofs, relationships, verification, concurrent mutation constraints, and account infrastructure.
The expanded read-only restore test also accepts complete proof and attempt structures.

These are disposable-database integration checks, not deployment verification.

Scoped equivalence declarations can connect two public versions within a private declaring project without owning either endpoint.
Directed declarations retain the local-source restriction.
Reads check both endpoints and the declaration's own scope.
Public endpoints do not make a private declaration public.

Exact and scoped version reads, embedded object versions, paginated object history, and discovery hits share the kind-discriminated `ObjectVersionRead` contract.
Attempt-history pages also return that contract and filter exact targets with `target_object_version_id`.
Browser attempt views derive their structure from canonical pins.
Public attempts retain released content and masked attribution, including when read alongside private attempts in a member project.
Without an exact target filter, attempt history spans visible target versions.
A private current head does not hide the history of an already public target.

Explicitly selecting that private head still requires member access.
History batches its child queries.
Public projections mask private attribution and relationship scope fields within that shared shape.

Public object reads select the latest currently accessible released revision, including when the actual current revision is private.
Public history selects only accessible revisions, masks inaccessible bases, and uses frozen release content.
Displayed current revision IDs must not reveal a private head.
Public object search matches the latest visible version before pagination, rather than requiring the actual head to be public.
Member search still matches the current private head in authorized projects.

New direct research releases use projection version 4.
Selective publication uses version 5.
These extend the respective historical versions 2 and 3 with schema version and rationale.
Older formats remain readable without rewriting stored JSON or digests.

New stored projections omit derived structural relationships.
The API calculates these relationships when it responds.
Catalogue reads accept direct research format 4 where they previously accepted format 2.

Selective formats remain distinct.
Recovery validation recognizes all five formats.
Recovery verification scans canonical relationships, including structural pins in its item bound.
Directed links require source-scope coherence.
Independently scoped equivalence does not require either endpoint to own the declaration.
Structural pins must share their source version's contribution and authorship.

Restore checks also require complete structured proof/attempt relationship sets:

- Proof conclusions and premises must be attached statements.
- Attempts must have a non-attempt target.
- Any result must be a newer version of that target's object.
  Historical records without typed proof/attempt structure remain supported.

## Live API migration

The accepted target uses `/versions`, explicit `object_version_id` references, `current_object_version_id`, `previous_object_version_id`, and `change_summary` throughout research HTTP contracts and tools.
Create-version commands require `expected_current_object_version_id`, which is not a persisted version field.
The core routes now use these names.
Create/update requests supply complete snapshots, including explicit structural relationships.
Omitted fields do not inherit.
Scoped record reads also return the shared version response.

Catalogue metadata is separate from version content.
Hosted tools use `get_object_version` and `write_object_version`.
Pinned context still limits their visible endpoints, with omitted structural relationship counts reported.
Receipt projections use current terminology without changing stored identities.
Direct comment requests use `object_version_id`.
Scoped comment and progress requests, responses, and exact-version query filters use `object_version_id`.

The HTTP boundary translates commands into the original internal models, preserving retry digests and frozen publication comments and progress entries.
Hosted `report_progress` also uses `object_version_id` on input and output, translating to its historical command before grant, pinned-context, lease, and retry checks.
Summary HTTP requests and responses and hosted `write_summary` use `source_object_version_ids` for cited research snapshots.
The summary's own `current_revision` and `base_revision_id` still refer to its separate authored-summary history.
Historical summary models and publication encodings retain `source_revision_ids` internally.
Hosted summary-creation retries return the original summary revision without requiring a new edit grant or consuming another mutation.

New edits still require an explicit editable-object grant.
Retries recheck the run and sources.
Notification items and derived progress-summary items identify `object_version_id`.
Stored delivery events, notification rows, summary inputs, and input digests keep their original encoding.
Current visibility is still checked at read time.
Retained external-run history exposes `input_object_version_ids`.

The historical run rows keep their original input-list encoding.
Hosted message requests use `context_object_version_ids`, and requested public grants use `public_target_object_version_ids`.
The HTTP boundary translates grants to their historical encoding before current-policy validation, persistence, and retry comparisons.
Stored run inputs and grant digests remain unchanged.
The API rejects legacy request field names.
Owner-only run/proposal context inspection returns `object_version_ids` and typed `object_versions`, batching private member inputs separately from frozen public inputs.

This richer owner inspection does not broaden agent capabilities: tool reads still clip unpinned relationships and private attribution.
Manifest IDs, exact pin sets, and historical digests are unchanged, and cached context still rechecks current authorization.
Endorsement and correspondence requests and history/current responses identify `object_version_id`.
Correspondence also identifies `statement_object_version_id`.
Their existing assessor histories and authorization rules are unchanged.
HTTP commands translate into the historical receipt encoding before policy and retry checks.

Live writes accept no legacy research-reference aliases.
Verification submission and job responses identify `work_target_object_version_id`, `research_attempt_object_version_id`, and input `object_version_id`.
Human HTTP, hosted verification tools, and private controller claim/renew/complete responses use the same live job schema.
The controller gateway converts the transport response back to the original internal specification before byte-manifest checks and sandbox execution.
Stored jobs, input manifests, request digests, completion payloads, quotas, and lease fencing are unchanged.
Invalid paths, ambiguous input identities, and incompatible job purposes still use the shared original validator.

The new request boundary rejects legacy reference fields.
Publication preview and confirmation commands select `object_version_ids`.
Preview, confirmation, member history, and public manifest envelopes expose `required_object_version_ids` and the same selection terminology.
The boundary translates commands before digest and retry checks.
Stored selection JSON, preview digests, and receipt encodings remain unchanged.
Summary selection still uses `summary_revision_ids`, identifying its independent authored-summary history.

Nested publication `public_fields` expose `object_versions` using the shared typed version contract and `relationships` using canonical directed/bidirectional endpoints.
Comments, progress, summary sources, and artifact links use the same explicit object-version names as their standalone APIs.
Preview, confirmation, member history, and public history project the selected snapshot without rewriting stored JSON.
The preview digest remains an opaque confirmation token over the historical encoding, not a hash clients can recompute from the new wire shape.
Frozen content, relationship descriptions, and display attribution remain unchanged when current rows or account names differ.
Public version projections mask account/contribution IDs and private predecessor versions.

Member version reads retain their authorized history and attribution.
Activity feeds identify `object_version_id` and `previous_object_version_id`.
Public feeds mask inaccessible predecessor versions.
Member feeds retain the authorized chain.
Stored activity events keep their historical column names.
Public activity titles and excerpts use released content, loaded in batches for each page.

Member feeds retain their authorized project content.
Progress-summary titles, excerpts, and reported outcomes use the same frozen release-aware batch reader as exact public versions, rather than raw rows.
Hosted comment writes use `comment_on_object_version` and `object_version_id`, while retaining the existing granted destination, pinned context, lease and retry checks.
Historical stored comment encodings are unchanged.
Artifact attachment writes, lists, and public metadata use `object_version_id`, `source_object_version_id`, and `attempt_object_version_id`.
Uploads to the Library use `statement_object_version_id`.

Exact attachments live at `/versions/{object_version_id}/attachments`.
Frozen artifact publication models remain separate from live projections, preserving stored fields and digests.
Project references distinguish their own immutable pin history from research history: `reference_version_id` and `previous_reference_version_id` identify the pin history, while `object_version_id` identifies the exact research snapshot.
`latest_object_version_id` reports an available current Library formulation.
Reference upgrades require `expected_current_reference_version_id`, not a research-object version guard.
Stored reference rows, event payloads, and retry digests retain their original encoding.

Record moderation commands (Library research and public-project operator moderation) require `expected_current_object_version_id`.
Their audit responses identify `object_version_id`.
Moderator authority, stored audit rows, outbox facts, and retry encodings are unchanged.
Catalogue version creation uses `POST /catalogue/{entry_id}/versions` and `expected_current_object_version_id`.
Exact catalogue history is available at `/catalogue/{entry_id}/versions/{object_version_id}`.
Edited correction decisions use the same formulation guard.

These commands translate into the historical stored encoding so existing receipts and correction proposals remain valid.
Catalogue promotion selects `object_version_id`.
Catalogue moderation requires `expected_current_object_version_id`.
Their historical receipt encodings remain unchanged.
Catalogue entry, exact history, and list responses embed `object_version` using the shared typed version contract.
Source and human-review metadata remain alongside it.

The version itself supplies its number and creation time.
Historical statement-only release JSON is unchanged.
Catalogue and Library pages batch their public version projections while retaining the requested order and exact history selections.
Query-count tests compare single-item and eight-item pages.
A hide-during-projection regression checks the per-item fallback omits an entry that becomes unavailable.
For release format 1, account IDs absent from the release remain masked in both exact and catalogue reads.

Catalogue audit responses identify `object_version_id`.
Correction-decision responses identify `suggestion_object_version_id` and `decided_object_version_id`.
Their stored rows, events, and retry digests are unchanged.
Catalogue admission, promotion, version creation, and moderation responses identify `entry_id` and `object_version_id`.
The internal mutation result and stored retry encoding retain their historical field names.
Live responses do not include a `revision_id` alias.

Project and Library research forms create full snapshots through `/objects`.
The legacy `POST /records` mutation is removed (scoped record reads remain).
Correction creation supplies `catalogue_suggestion` command metadata outside snapshot content, using `expected_current_object_version_id` for its exact proposed base.
It remains a public NOTE attached to that admitted Library statement.
Historical stored correction proposals retain their original encoding.
Bounded title resolution uses `/research/versions/display`, accepts `object_version_ids`, and returns `object_version_id` on each display entry.

It preserves requested order, rejects duplicate IDs, enforces project access, and reads public titles from released projections.
The live relationship wire union has explicit directed and bidirectional endpoint shapes.
Both write and read contracts accept `EQUIVALENT_TO` only in their bidirectional branch.
Browser scoped relationship creation uses `/relations` with an explicit project or Library destination.
`/scoped-relations` is removed.
The historical `VersionRelationship` remains an internal compatibility projection, not the canonical attributed relationship entity.

Project dependent reads select `object_version_id` and return canonical relationship responses.
They include incoming directed declarations, not equivalence declarations.
Advancing an object's current version does not move links pinned to an earlier version.

The API introduction and portable Polycolab skill use object-version routes, complete snapshot writes, explicit concurrency guards, and version-pinned evidence.
Tests exercise the skill and developer guide creation examples through the HTTP API, including exact reads and idempotent replay.

Real-service checks cover exact pins, external-agent retries and revocation, private-context non-disclosure, and coordinated restoration of versions, relationships, artifacts, and credentials.
Follow the [system test guide](../../tests/system/README.md) for prerequisites and scope.
Local deterministic-provider checks do not establish deployment acceptance.

Full version responses already share a kind-discriminated schema across exact, history, and embedded reads.
The document editor and history panel label research snapshots as versions and display the stable agent name for agent authorship.
The browser research adapter exposes `createVersion`, `listVersions`, and `ObjectVersion`.
Document, record-edit, history, and public-project consumers use these names directly rather than revision aliases.
This naming cleanup preserves wire routes, full snapshot payloads, pagination, and retry-key behavior.
Record-edit controls, Library history, public record headings, graph links, and dependency controls label research snapshots as versions.

Human-note and summary revision labels remain independent of this research terminology.
Graph node links preserve the displayed exact version instead of navigating to a newer object head.
Mocked-browser checks exercise lazy neighborhood loading, version-pinned links, and the readable directed/bidirectional relationship list.
The document view resolves its exact-version URL parameter, rejects versions of a different object, and reports unavailable versions without falling back to the current head.
History selection updates the URL.
Returning to current removes the pin.

Mocked-browser tests cover selection, reload, missing/mismatched versions, and mobile history navigation.
The source editor, proof view, public research lists, selectors, relationship panels, contribution controls, verification/evidence views, and Library/reference workflows display version terminology.
Summary source pins use version terminology while the summary's own revision history and human-note revisions remain distinct.
Internal view-model aliases and legacy browser deep-link URLs remain compatible.
They are not accepted legacy research API write fields.
These checks do not replace real-service or deployment verification.

The mocked document-conflict workflow uses current version endpoints.
It verifies draft restoration after navigation and explicit rebasing.
It also verifies that the next complete snapshot preserves the new base's assumptions and exact structural pins.
The code-source browser workflow also uses complete version commands.
It verifies that a transient failure preserves the retry body/key, metadata, and structural pins.
It also verifies that navigation to the returned saved version remains available after the failure.

Browser and agent consumers use the same breaking wire-contract mapping described above.
Stored proposal payloads and decision retry digests remain unchanged.
Historical receipt/release decoders and separate public/member projections are retained.

The input foundation for that cutover is now in `agents/proposal_version_schemas.py`: complete object snapshots, guarded `CREATE_OBJECT_VERSION`, directed/bidirectional `CREATE_RELATIONSHIP`, and version-pinned comments.
It shares snapshot validation and endpoint shapes with direct contributions.
Proposal scope, not caller-supplied destination or authorship, determines where changes belong.
Service submission and human review now validate these payloads alongside the historical decoder, mapping new operation names to the existing persisted operation enum.
Application uses canonical complete-snapshot and relationship writers in the review transaction.
Structural targets must be in the run manifest at submission and review, including human-edited payloads.

Tests cover complete content, lineage, agent attribution, symmetric declarations, atomic decision replay, and out-of-manifest rejection.
Existing stored payloads are not rewritten.

The hosted `submit_proposal` tool now advertises the full discriminated version-proposal schema and rejects legacy write shapes.
Its deterministic provider fixture submits complete snapshots.
The browser review editor renders and edits nested snapshot text.
It preserves guards, typed metadata, and structural relationships.
It retains identical retry bodies and keys after conflicts.
Individual and batch HTTP review edits now accept only the discriminated version-command union.

Legacy flat edits and incomplete snapshots return 422 before mutation.
Historical proposals remain readable and may be accepted unchanged.
Editing them requires a complete command satisfying current write validation.
`agents/proposal_projections.py` supplies the historical-to-version read adapter for that HTTP cutover.
Historical edits resolve metadata and inherited statement attachments from their exact base, not the object's current head.
The adapter retains proof premise order and symmetric relationship endpoints.

The adapter preserves empty historical text.
It does not synthesize text to satisfy new-write validation.
Tests compare a projected historical edit with its actual accepted result.

All HTTP proposal detail and decision responses now use this adapter and a discriminated payload schema, including kind-specific snapshot content.
Wire operation labels are `CREATE_OBJECT_VERSION` and `CREATE_RELATIONSHIP`.
Persisted enum values and payloads are unchanged.
Read schemas retain historical content without imposing new-write text limits.

Unchanged browser acceptances omit the edited payload, so the stored proposal remains authoritative.
Actual edits send the complete payload.
Returning a draft to its original content restores unchanged-acceptance semantics.
Changed text, null values, or ordered pins are not silently discarded.
Retry keys remain stable for identical decision bodies and change when the selected edit changes.
Stored historical decision digests are not rewritten.

The API recognizes a version-shaped retry of a committed historical edit only under these conditions:

- It exactly matches the stored edit's projection.
- The original digest, reviewer, key, action, and complete batch selection still match.
  Changed content or an unchanged-acceptance substitute conflicts.
  Historical content that cannot satisfy current write validation (for example, empty required assumptions) cannot be retried as an edited command.
  Read the committed decision to recover its outcome.
  Legacy HTTP write shapes remain rejected.
  Tests cover individual and mixed-batch version, equivalence, and comment retries and verify that stored payloads and decision digests remain unchanged.

Agent contribution provenance uses `OBJECT_VERSION` and `OBJECT_VERSION_RELATIONSHIP` in its entity-type path parameter and response.
The endpoint retains project membership authorization and reads existing contribution links without rewriting their historical entity encodings.
Stale proposal errors identify the current research snapshot with `current_object_version_id`.
The historical `current_revision_id` wire alias is not emitted.
Separate human-note and summary revision streams retain their own revision terminology.

History search, diff endpoints, patch storage, branching, and assertion withdrawal/supersession are outside this foundation.
Dedicated human-note and summary streams, comments, artifacts, assurance, and execution jobs remain separate entities.
