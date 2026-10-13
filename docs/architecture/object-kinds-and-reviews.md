# Object kinds and version reviews

The live API uses the object kinds and version reviews described below.
Immutable historical encodings remain readable.

## Objects

The live API accepts seven kinds: `PROBLEM`, `STATEMENT`, `PROOF`, `DEFINITION`, `NOTE`, `FORMALIZATION`, and `ATTEMPT`.
Statement content has a `statement_label`: `CLAIM` (default), `CONJECTURE`, `LEMMA`, `PROPOSITION`, `THEOREM`, or `COROLLARY`.
A label describes the author's mathematical role, not a verification result.

A Proof keeps the same identity from sketch to completion.
It pins one exact Statement conclusion and exact premises, with `direction: SUPPORTS | REFUTES` and independently reported progress.
A refutation is a Proof, not a separate Counterexample kind.
Examples and exploratory computations can be Notes.
An Attempt pins its work target.
Its `RESULT` is a revision of that target.

Multiple `EVIDENCE` relationships with `evidence_role: OUTPUT` identify other objects produced by the activity.

Executable source is a capability: content may declare `source_language: LEAN | PYTHON`.
Execution admission checks this metadata or the legacy source kind.
Execution results are evidence, not human/AI assessments or an automatic truth signal.
Trusted formal assurance remains unavailable until its verification pipeline is implemented.
Arbitrary agent assertions cannot set it.

## Historical compatibility

Stable UUIDs, prior content, receipts and publication snapshots are not rewritten.
A generated, indexed `canonical_kind` on object identities maps CLAIM to STATEMENT, PROOF_SKETCH to PROOF, and IDEA/DISCUSSION/COUNTEREXAMPLE/COMPUTATION to NOTE.
Existing PROOF stays PROOF.
New live writes use the canonical vocabulary.
The historical codec retains CLAIM/PROOF_SKETCH storage values where needed.

New versions store semantic metadata alongside their immutable content.
Authorized projections return canonical kinds and `legacy_kind` where a historical spelling was mapped.
Legacy computations retain Python source semantics.
The historical publication encoding excludes empty added metadata, so old digests remain reproducible.
PostgreSQL and local SQLite upgrades add these fields without rewriting historical payloads.
Downgrade requires restoring the pre-upgrade backup.

## Reviews

`POST /api/v1/reviews` appends an exact-version assessment or withdrawal, with an idempotency key.
Required fields are target version and outcome.
Scope defaults to the whole version.
Detailed assessments require rationale, while REVIEWED and withdrawal accept an empty comment.
Optional evidence consists of exact accessible version IDs.
The simplified UI writes REVIEWED with an optional comment and server-derived reviewer identity.

It makes no correctness claim.
Existing detailed assessments retain outcomes SUPPORTS, ISSUES_FOUND and INCONCLUSIVE.
Withdrawal requires `withdrawn: true` and a null outcome.
Actor identity is server-derived.
Hosted reviews retain the recorded model.
External agents with no trustworthy model provenance show no model.

Self-reviews remain explicitly identified.

`GET /api/v1/reviews/{object_version_id}` provides bounded chronological history.
`current=true` returns the latest visible event per reviewer, including withdrawals.
`project_only=true` with an authorized project selects its own review events for publication.
`POST /api/v1/reviews/summary` accepts at most 128 unique version IDs and returns human/AI outcome counts and self-review counts.
Withdrawals remove the reviewer's active assessment.
Conflicting reviewers remain visible.

Neither new versions nor dependent objects inherit reviews.

Humans use project contribution authority.
External keys must explicitly opt into `allow_reviews`.
Hosted grants must include `REVIEW_RESEARCH` to advertise and execute `review_object_version`.
Existing sponsor, scope, input, lease, mutation-budget and retry checks still apply.
Review writes and contribution receipts share a transaction.
Database triggers reject review updates/deletions.

Private review visibility is independent from target visibility.
Unauthorized evidence hides the whole assessment from that read scope.
Publication includes reviews only through explicit `review_ids`.
Selected review targets and evidence join the dependency closure.
Publishing an object alone never publishes its private reviews.
Legacy endorsements and correspondence retain their own history and are not converted into assessments.

## UI

Creation, editing and search use canonical kinds.
The object inspector and map share a compact version-review panel: reviewer identity, Mark as reviewed, and an optional comment.
The Reviewed menu supports editing the comment or removing the review.
History and retry handling remain available.

The server supplies reviewer ownership.
The browser never infers it from display names.
Map nodes use blue, violet, slate and beige kind colors.

Proofs use titled diamond nodes at about two-thirds of a Statement node’s width.
Notes use compact list rows with an inline reader in the right panel.
Opening a full note uses same-tab navigation.
Reported progress uses separate blue, amber, green and brick-red dots centered on the right edge of each shape.
It never implies verification.
Contributors can change reported progress in the object inspector’s Progress tab.

Saving creates a new version with an optimistic head check and preserves content and exact structural relationships.
Failure explanations are optional.

The map displays one node per stable object, using its current version for the title and signals.
The map projects historical relation endpoints onto those nodes for drawing only.
It combines duplicate visual edges.
Relationship details retain the original exact-version pins.
Human and AI review signals use person and sparkle icons.

Indicators and tooltips show review presence and counts only, including historical assessments without exposing outcome labels or outcome colors.
The legend lists Human reviewed and AI reviewed.
Reported progress retains its separate status colors.
Review indicators open the inspector.
Stored assessment history remains unchanged.

Notes, Attempts and Formalizations appear in the focused object's right-panel tabs instead of as map nodes.
The diagram and its object browser contain the remaining kinds.
The Notes and Attempts tabs match stable object UUIDs, so their context remains available after the parent gains a new version.
Formalizations attach to exact versions through structural ATTACHMENT links.
The Formalizations tab only shows links to the selected version and does not carry them forward.
`content.attached_object_ids` adds explicit object attachments to Notes and Attempts.

Existing exact-version attachments resolve to their parent UUIDs.
Attempts retain their worked-on TARGET version as provenance.
Attachment writes check target access, and publication includes the target's selected current version in its dependency closure.
An object attachment does not advance or rewrite an Attempt's worked-on version.
Historical API kind names use the same canonical labels, colors and shapes during the migration.

## Simplified project relationships

Project relationship editors and views use Depends on, Uses, Proved by, and Refuted by.
Diagrams place the object above its supporting material: statement → proof → premises.
Proved by and Refuted by reverse canonical PROVES/REFUTES endpoints for display and reverse them back when writing.
Proof CONCLUSION pins use that exact version's SUPPORTS/REFUTES direction.
PREMISE pins display as Depends on.
Unknown historical proof directions are not guessed.

Generic attachments and other relationship types are hidden in these views.
Notes, Attempts, and Formalizations retain their inspector tabs.
The views deduplicate equivalent structural and declaration edges for display.
Incoming links appear under Referenced by, while connection details retain every original exact-version endpoint.
Stored links and the public API remain unchanged.
The views retain cycles and do not enforce a strict tree.
