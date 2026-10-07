"""Human-confirmed selective publication of exact private research closures."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from polycolab.access.actors import Actor, ActorKind
from polycolab.access.authorization import (
    WorkspaceAction,
    lock_workspace_authorization,
    require_publication,
    workspace_policy,
)
from polycolab.artifacts.contracts import PublishedArtifactLinkRead, PublishedArtifactRead
from polycolab.db.models import (
    SqlArtifact,
    SqlArtifactResearchLink,
    SqlAttemptEvidenceLink,
    SqlContributionEnvelope,
    SqlObjectRevision,
    SqlPlatformAgentVersion,
    SqlProofSketchPremise,
    SqlProofSketchRevision,
    SqlPublicationArtifactMember,
    SqlPublicationComment,
    SqlPublicationManifest,
    SqlPublicationProgress,
    SqlPublicationRelation,
    SqlPublicationRevision,
    SqlPublicationSummary,
    SqlPublicRelease,
    SqlRelationAssertion,
    SqlResearchAttachment,
    SqlResearchAttemptRevision,
    SqlResearchComment,
    SqlResearchObject,
    SqlResearchProgressUpdate,
    SqlResearchScope,
    SqlResearchSummary,
    SqlResearchSummaryRevision,
    SqlSummarySourceRevision,
    SqlUser,
)
from polycolab.db.models.reviews import SqlObjectReview, SqlPublicationReview
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import ArtifactState
from polycolab.platform import mutation_keys
from polycolab.platform.outbox import canonical_digest
from polycolab.research.activity import (
    _comment_read,
    _progress_read,
    _summary_revision_read,
)
from polycolab.research.contracts import (
    PublicationConfirm,
    PublicationFields,
    PublicationManifestPage,
    PublicationManifestRead,
    PublicationPreview,
    PublicationSelection,
    PublicPublicationManifestRead,
    PublicPublicationSelection,
    PublishedRelationRead,
)
from polycolab.research.contributions import human_contribution
from polycolab.research.objects import ResearchNotFound
from polycolab.research.records import decode_cursor, encode_cursor, record_read
from polycolab.research.reviews import read as review_read
from polycolab.workspaces.service import DomainConflict

MAX_CLOSURE = 128


def _publisher_id(actor: Actor) -> UUID:
    require_publication(actor)
    if actor.kind is not ActorKind.HUMAN or actor.human_user_id is None:
        raise ResearchNotFound
    return actor.human_user_id


def _authorize(
    session: Session, *, actor: Actor, project_id: UUID, lock: bool
) -> tuple[UUID, SqlResearchScope]:
    user_id = _publisher_id(actor)
    if lock:
        lock_workspace_authorization(
            SqlAlchemyTransaction(session), project_id=project_id, user_id=user_id
        )
    workspace_policy.require_scope(
        SqlAlchemyTransaction(session), project_id, user_id, WorkspaceAction.MANAGE_SETTINGS
    )
    scope = session.scalar(
        select(SqlResearchScope).where(SqlResearchScope.project_id == project_id)
    )
    if scope is None:
        raise ResearchNotFound
    return user_id, scope


def _project_revision(session: Session, revision_id: UUID, project_id: UUID) -> SqlObjectRevision:
    row = session.get(SqlObjectRevision, revision_id)
    if row is None or row.project_id != project_id:
        raise ResearchNotFound
    return row


def _closure(
    session: Session, *, scope_id: UUID, selected_ids: list[UUID]
) -> list[SqlObjectRevision]:
    pending = list(selected_ids)
    found: dict[UUID, SqlObjectRevision] = {}
    while pending:
        revision_id = pending.pop(0)
        if revision_id in found:
            continue
        revision = session.get(SqlObjectRevision, revision_id)
        if revision is None:
            raise ResearchNotFound
        if revision.ownership_scope_id != scope_id:
            from polycolab.research.records import public_revision

            public_revision(session, revision.id)
        found[revision.id] = revision
        if len(found) > MAX_CLOSURE:
            raise DomainConflict("publication dependency closure exceeds 128 revisions")
        dependencies = set(
            session.scalars(
                select(SqlResearchAttachment.statement_revision_id).where(
                    SqlResearchAttachment.revision_id == revision.id
                )
            )
        )
        attached = revision.semantic_metadata.get("attached_object_ids", [])
        if isinstance(attached, list):
            for object_id in attached:
                parent = session.get(SqlResearchObject, UUID(str(object_id)))
                if parent is None or parent.current_revision_id is None:
                    raise ResearchNotFound
                dependencies.add(parent.current_revision_id)
        sketch = session.get(SqlProofSketchRevision, revision.id)
        if sketch is not None:
            dependencies.add(sketch.conclusion_revision_id)
            dependencies.update(
                session.scalars(
                    select(SqlProofSketchPremise.premise_revision_id).where(
                        SqlProofSketchPremise.sketch_revision_id == revision.id
                    )
                )
            )
        attempt = session.get(SqlResearchAttemptRevision, revision.id)
        if attempt is not None:
            dependencies.add(attempt.target_revision_id)
            dependencies.update(
                session.scalars(
                    select(SqlAttemptEvidenceLink.evidence_revision_id).where(
                        SqlAttemptEvidenceLink.attempt_revision_id == revision.id
                    )
                )
            )
            if attempt.result_revision_id is not None:
                dependencies.add(attempt.result_revision_id)
        pending.extend(sorted(dependencies - found.keys(), key=str))
    return [found[value] for value in sorted(found, key=str)]


def _relation_read(session: Session, row: SqlRelationAssertion) -> PublishedRelationRead:
    author = session.get(SqlUser, row.created_by_user_id)
    envelope = session.get(SqlContributionEnvelope, row.contribution_id)
    if author is None or envelope is None:
        raise ResearchNotFound
    agent = (
        session.get(SqlPlatformAgentVersion, envelope.agent_version_id)
        if envelope.agent_version_id
        else None
    )
    return PublishedRelationRead(
        id=row.id,
        source_revision_id=row.source_revision_id,
        target_revision_id=row.target_revision_id,
        relation_type=row.relation_type,
        rationale=row.rationale,
        author_display_name=author.display_name,
        actor_kind=envelope.actor_kind.value,
        agent_display_name=agent.display_name if agent else None,
        created_at=row.created_at,
    )


def _selected_artifacts(
    session: Session,
    *,
    scope_id: UUID,
    artifact_ids: list[UUID],
    lock: bool,
) -> list[tuple[SqlArtifact, list[SqlArtifactResearchLink]]]:
    if not artifact_ids:
        return []
    query = (
        select(SqlArtifact)
        .where(
            SqlArtifact.id.in_(artifact_ids),
            SqlArtifact.ownership_scope_id == scope_id,
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    by_id = {row.id: row for row in session.scalars(query)}
    if len(by_id) != len(artifact_ids):
        raise ResearchNotFound
    selected: list[tuple[SqlArtifact, list[SqlArtifactResearchLink]]] = []
    for artifact_id in artifact_ids:
        artifact = by_id[artifact_id]
        if artifact.state is not ArtifactState.COMMITTED:
            raise DomainConflict("selected artifact is not committed")
        links = list(
            session.scalars(
                select(SqlArtifactResearchLink)
                .where(SqlArtifactResearchLink.artifact_id == artifact_id)
                .order_by(SqlArtifactResearchLink.created_at, SqlArtifactResearchLink.id)
            )
        )
        if not links:
            raise DomainConflict("selected artifact has no research binding")
        selected.append((artifact, links))
    return selected


def _artifact_read(
    session: Session, artifact: SqlArtifact, links: list[SqlArtifactResearchLink]
) -> PublishedArtifactRead:
    author = session.get(SqlUser, artifact.created_by_user_id)
    envelope = session.get(SqlContributionEnvelope, artifact.contribution_id)
    if author is None or envelope is None:
        raise ResearchNotFound
    agent = (
        session.get(SqlPlatformAgentVersion, envelope.agent_version_id)
        if envelope.agent_version_id
        else None
    )
    return PublishedArtifactRead(
        id=artifact.id,
        sha256=artifact.sha256,
        byte_length=artifact.byte_length,
        media_type=artifact.media_type,
        source_revision_id=artifact.source_revision_id,
        links=[
            PublishedArtifactLinkRead(
                revision_id=link.revision_id,
                attempt_revision_id=link.attempt_revision_id,
                role=link.role,
            )
            for link in links
        ],
        author_display_name=author.display_name,
        actor_kind=envelope.actor_kind.value,
        agent_display_name=agent.display_name if agent else None,
        created_at=artifact.created_at,
        content_path=f"/api/v1/artifacts/{artifact.id}/content",
    )


def _build(
    session: Session, *, actor: Actor, selection: PublicationSelection, lock: bool = False
) -> PublicationPreview:
    _, scope = _authorize(session, actor=actor, project_id=selection.project_id, lock=lock)
    for revision_id in selection.revision_ids:
        _project_revision(session, revision_id, selection.project_id)
    revisions = _closure(
        session,
        scope_id=scope.id,
        selected_ids=selection.revision_ids,
    )
    closure_ids = {row.id for row in revisions}

    summaries: list[SqlResearchSummaryRevision] = []
    for summary_id in selection.summary_revision_ids:
        summary_row = session.get(SqlResearchSummaryRevision, summary_id)
        stream = session.get(SqlResearchSummary, summary_row.object_id) if summary_row else None
        if summary_row is None or stream is None or stream.ownership_scope_id != scope.id:
            raise ResearchNotFound
        if not any(item.object_id == summary_row.object_id for item in revisions):
            raise DomainConflict("selected summary requires a selected revision of its object")
        sources = list(
            session.scalars(
                select(SqlSummarySourceRevision.source_revision_id).where(
                    SqlSummarySourceRevision.summary_revision_id == summary_row.id
                )
            )
        )
        revisions = _closure(
            session,
            scope_id=scope.id,
            selected_ids=[*closure_ids, *sources],
        )
        closure_ids = {item.id for item in revisions}
        summaries.append(summary_row)

    comments: list[SqlResearchComment] = []
    optional_dependencies: set[UUID] = set()
    for comment_id in selection.comment_ids:
        comment_row = session.get(SqlResearchComment, comment_id)
        if comment_row is None or comment_row.ownership_scope_id != scope.id:
            raise ResearchNotFound
        optional_dependencies.add(comment_row.revision_id)
        comments.append(comment_row)
    selected_reviews: list[SqlObjectReview] = []
    for review_id in selection.review_ids:
        review = session.get(SqlObjectReview, review_id)
        if review is None or review.ownership_scope_id != scope.id:
            raise ResearchNotFound
        optional_dependencies.add(review.object_version_id)
        optional_dependencies.update(UUID(value) for value in review.evidence_object_version_ids)
        selected_reviews.append(review)
    progress: list[SqlResearchProgressUpdate] = []
    for progress_id in selection.progress_ids:
        progress_row = session.get(SqlResearchProgressUpdate, progress_id)
        if progress_row is None or progress_row.ownership_scope_id != scope.id:
            raise ResearchNotFound
        optional_dependencies.add(progress_row.revision_id)
        progress.append(progress_row)
    relations: list[SqlRelationAssertion] = []
    for relation_id in selection.relation_ids:
        relation_row = session.get(SqlRelationAssertion, relation_id)
        if relation_row is None or relation_row.ownership_scope_id != scope.id:
            raise ResearchNotFound
        optional_dependencies.update(
            (relation_row.source_revision_id, relation_row.target_revision_id)
        )
        relations.append(relation_row)

    selected_artifacts = _selected_artifacts(
        session,
        scope_id=scope.id,
        artifact_ids=selection.artifact_ids,
        lock=lock,
    )
    for artifact, links in selected_artifacts:
        if artifact.source_revision_id is not None:
            optional_dependencies.add(artifact.source_revision_id)
        for link in links:
            optional_dependencies.add(link.revision_id)
            if link.attempt_revision_id is not None:
                optional_dependencies.add(link.attempt_revision_id)

    if optional_dependencies - closure_ids:
        revisions = _closure(
            session,
            scope_id=scope.id,
            selected_ids=[*closure_ids, *optional_dependencies],
        )
        closure_ids = {item.id for item in revisions}

    fields = PublicationFields(
        reviews=[review_read(review) for review in selected_reviews],
        records=[record_read(session, row, selection.project_id) for row in revisions],
        summaries=[_summary_revision_read(session, row, selection.project_id) for row in summaries],
        comments=[_comment_read(session, row) for row in comments],
        progress=[_progress_read(session, row) for row in progress],
        relations=[_relation_read(session, row) for row in relations],
        artifacts=[
            _artifact_read(session, artifact, links) for artifact, links in selected_artifacts
        ],
    )
    required = [row.id for row in revisions if row.id not in set(selection.revision_ids)]
    digest_body = {
        "selection": selection.model_dump(mode="json"),
        "required_revision_ids": [str(value) for value in required],
        "public_fields": fields.model_dump(mode="json"),
    }
    return PublicationPreview(
        selection=selection,
        required_revision_ids=required,
        public_fields=fields,
        preview_digest=canonical_digest(digest_body),
    )


def preview(
    session: Session, *, actor: Actor, selection: PublicationSelection
) -> PublicationPreview:
    return _build(session, actor=actor, selection=selection)


def confirm(
    session: Session,
    *,
    actor: Actor,
    payload: PublicationConfirm,
    key: str,
    verified_artifact_ids: frozenset[UUID] = frozenset(),
) -> PublicationManifestRead:
    user_id = _publisher_id(actor)
    selection = PublicationSelection.model_validate(
        payload.model_dump(exclude={"preview_digest", "reason"})
    )
    actor_key = f"human:{user_id}"
    body = payload.model_dump(mode="json")
    if frozenset(selection.artifact_ids) != verified_artifact_ids:
        raise DomainConflict("selected artifact bytes were not verified")
    try:
        mutation_keys.lock_key(session, actor_key, "publication.confirm", key)
        existing = mutation_keys.receipt(session, actor_key, "publication.confirm", key, body)
        if existing is not None:
            manifest = session.get(SqlPublicationManifest, UUID(existing.resource_ids[0]))
            if manifest is None:
                raise ResearchNotFound
            session.commit()
            return _manifest_read(session, manifest)
        built = _build(session, actor=actor, selection=selection, lock=True)
        if built.preview_digest != payload.preview_digest:
            raise DomainConflict("stale publication preview")
        if (
            session.scalar(
                select(SqlPublicationManifest.id).where(
                    SqlPublicationManifest.preview_digest == built.preview_digest
                )
            )
            is not None
        ):
            raise DomainConflict("publication preview was already confirmed")
        scope = session.scalar(
            select(SqlResearchScope).where(SqlResearchScope.project_id == payload.project_id)
        )
        if scope is None:
            raise ResearchNotFound
        envelope = human_contribution(
            session,
            user_id=user_id,
            scope_id=scope.id,
            operation="publication.confirm",
        )
        manifest = SqlPublicationManifest(
            project_id=payload.project_id,
            ownership_scope_id=scope.id,
            preview_digest=built.preview_digest,
            contribution_id=envelope.id,
            created_by_user_id=user_id,
            selection=selection.model_dump(mode="json"),
            public_fields={
                "required_revision_ids": [str(value) for value in built.required_revision_ids],
                **built.public_fields.model_dump(mode="json", exclude_computed_fields=True),
            },
        )
        session.add(manifest)
        session.flush()
        selected = set(selection.revision_ids)
        all_revisions = [*selection.revision_ids, *built.required_revision_ids]
        records_by_id = {row.revision_id: row for row in built.public_fields.records}
        for position, revision_id in enumerate(all_revisions):
            revision = session.get(SqlObjectRevision, revision_id)
            if revision is None:
                raise ResearchNotFound
            session.add(
                SqlPublicationRevision(
                    manifest_id=manifest.id,
                    revision_id=revision_id,
                    position=position,
                    selected=revision_id in selected,
                )
            )
            existing_release = session.scalar(
                select(SqlPublicRelease).where(SqlPublicRelease.object_revision_id == revision_id)
            )
            if existing_release is None:
                public_fields = records_by_id[revision_id].model_dump(
                    mode="json", exclude_computed_fields=True
                )
                session.add(
                    SqlPublicRelease(
                        ownership_scope_id=revision.ownership_scope_id,
                        object_revision_id=revision.id,
                        contribution_id=envelope.id,
                        publication_manifest_id=manifest.id,
                        projection_version=5,
                        public_fields=public_fields,
                        public_fields_digest=canonical_digest(public_fields),
                    )
                )
        for position, value in enumerate(selection.summary_revision_ids):
            session.add(
                SqlPublicationSummary(
                    manifest_id=manifest.id, summary_revision_id=value, position=position
                )
            )
        for review_id in selection.review_ids:
            session.add(SqlPublicationReview(manifest_id=manifest.id, review_id=review_id))
        for position, value in enumerate(selection.comment_ids):
            session.add(
                SqlPublicationComment(manifest_id=manifest.id, comment_id=value, position=position)
            )
        for position, value in enumerate(selection.progress_ids):
            session.add(
                SqlPublicationProgress(
                    manifest_id=manifest.id, progress_id=value, position=position
                )
            )
        for position, value in enumerate(selection.relation_ids):
            session.add(
                SqlPublicationRelation(
                    manifest_id=manifest.id, relation_id=value, position=position
                )
            )
        # Public-release rows must exist before the membership trigger evaluates
        # the artifact's exact research bindings.
        session.flush()
        for position, value in enumerate(selection.artifact_ids):
            session.add(
                SqlPublicationArtifactMember(
                    manifest_id=manifest.id,
                    artifact_id=value,
                    position=position,
                )
            )
        mutation_keys.save(session, actor_key, "publication.confirm", key, body, [manifest.id])
        session.commit()
        session.refresh(manifest)
        return _manifest_read(session, manifest)
    except Exception:
        session.rollback()
        raise


def _manifest_read(session: Session, manifest: SqlPublicationManifest) -> PublicationManifestRead:
    publisher = session.get(SqlUser, manifest.created_by_user_id)
    if publisher is None:
        raise ResearchNotFound
    fields = dict(manifest.public_fields)
    raw_required = fields.pop("required_revision_ids", [])
    if not isinstance(raw_required, list):
        raise ResearchNotFound
    required = [UUID(str(value)) for value in raw_required]
    projected = PublicationFields.model_validate(fields)
    # Download URLs are transport metadata, not immutable research content.
    # Normalize retained manifests without rewriting their stored facts/digests.
    projected = projected.model_copy(
        update={
            "artifacts": [
                artifact.model_copy(
                    update={"content_path": f"/api/v1/artifacts/{artifact.id}/content"}
                )
                for artifact in projected.artifacts
            ]
        }
    )
    return PublicationManifestRead(
        id=manifest.id,
        project_id=manifest.project_id,
        preview_digest=manifest.preview_digest,
        selection=PublicationSelection.model_validate(manifest.selection),
        required_revision_ids=required,
        public_fields=projected,
        publisher_display_name=publisher.display_name,
        created_at=manifest.created_at,
    )


def public_manifest(session: Session, manifest_id: UUID) -> PublicPublicationManifestRead:
    manifest = session.get(SqlPublicationManifest, manifest_id)
    if manifest is None:
        raise ResearchNotFound
    internal = _manifest_read(session, manifest)
    from polycolab.research.records import public_revision

    for record in internal.public_fields.records:
        public_revision(session, record.revision_id)
    return PublicPublicationManifestRead(
        id=internal.id,
        preview_digest=internal.preview_digest,
        selection=PublicPublicationSelection.model_validate(
            internal.selection.model_dump(exclude={"project_id"})
        ),
        required_revision_ids=internal.required_revision_ids,
        public_fields=internal.public_fields,
        publisher_display_name=internal.publisher_display_name,
        created_at=internal.created_at,
    )


def public_artifact(
    session: Session, artifact_id: UUID
) -> tuple[SqlArtifact, PublishedArtifactRead]:
    members = list(
        session.scalars(
            select(SqlPublicationArtifactMember)
            .where(SqlPublicationArtifactMember.artifact_id == artifact_id)
            .order_by(SqlPublicationArtifactMember.manifest_id)
        )
    )
    for member in members:
        try:
            manifest = public_manifest(session, member.manifest_id)
        except ResearchNotFound:
            continue
        projected = next(
            (item for item in manifest.public_fields.artifacts if item.id == artifact_id),
            None,
        )
        artifact = session.get(SqlArtifact, artifact_id)
        if (
            projected is not None
            and artifact is not None
            and artifact.state is ArtifactState.COMMITTED
        ):
            return artifact, projected
    raise ResearchNotFound


def history(
    session: Session,
    *,
    actor: Actor,
    project_id: UUID,
    limit: int,
    cursor: str | None,
) -> PublicationManifestPage:
    _authorize(session, actor=actor, project_id=project_id, lock=False)
    query = select(SqlPublicationManifest).where(SqlPublicationManifest.project_id == project_id)
    if cursor:
        anchor = session.get(SqlPublicationManifest, decode_cursor(cursor))
        if anchor is None or anchor.project_id != project_id:
            raise DomainConflict("invalid cursor")
        query = query.where(
            or_(
                SqlPublicationManifest.created_at > anchor.created_at,
                and_(
                    SqlPublicationManifest.created_at == anchor.created_at,
                    SqlPublicationManifest.id > anchor.id,
                ),
            )
        )
    rows = list(
        session.scalars(
            query.order_by(SqlPublicationManifest.created_at, SqlPublicationManifest.id).limit(
                limit + 1
            )
        )
    )
    return PublicationManifestPage(
        items=[_manifest_read(session, row) for row in rows[:limit]],
        next_cursor=encode_cursor(rows[limit - 1].id) if len(rows) > limit else None,
    )
