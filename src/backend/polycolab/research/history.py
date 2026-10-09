"""Durable research history built from canonical saved resources, never request bodies."""

from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import event, exists, or_, select
from sqlalchemy.orm import Session, aliased

from polycolab.app.access import ResearchAccess
from polycolab.db.models import (
    SqlArtifactResearchLink,
    SqlCatalogueAudit,
    SqlContributionEnvelope,
    SqlExternalAgentCredential,
    SqlObjectRevision,
    SqlProject,
    SqlPublicationArtifactMember,
    SqlPublicationComment,
    SqlPublicationManifest,
    SqlPublicationProgress,
    SqlPublicationRelation,
    SqlPublicationRevision,
    SqlPublicationSummary,
    SqlPublicRelease,
    SqlRelationAssertion,
    SqlResearchActivityEvent,
    SqlResearchComment,
    SqlResearchProgressUpdate,
    SqlResearchScope,
    SqlResearchSummaryRevision,
    SqlSummarySourceRevision,
    WorkspaceVisibility,
)
from polycolab.db.models.relationships import SqlObjectVersionRelationship
from polycolab.research.records import public_condition

# These identifiers are persisted and participate in deterministic event IDs.
# They must remain stable when Python persistence classes are renamed.
SOURCE_KINDS: dict[type[Any], str] = {
    SqlObjectRevision: "ObjectRevision",
    SqlResearchComment: "ResearchComment",
    SqlRelationAssertion: "RelationAssertion",
    SqlArtifactResearchLink: "ArtifactResearchLink",
    SqlResearchProgressUpdate: "ResearchProgressUpdate",
    SqlResearchSummaryRevision: "ResearchSummaryRevision",
    SqlPublicRelease: "PublicRelease",
    SqlCatalogueAudit: "CatalogueAudit",
}
SOURCES = tuple(SOURCE_KINDS)


def from_source(
    session: Session, source: object, *, reconstructed: bool = False
) -> SqlResearchActivityEvent | None:
    revision: SqlObjectRevision | None
    if isinstance(source, SqlObjectVersionRelationship):
        if source.binding != "DECLARATION":
            return None
        declaration = session.get(SqlRelationAssertion, source.id)
        if declaration is None:
            return None
        source = declaration
    if isinstance(source, SqlObjectRevision):
        revision = source
        action = "object.created" if source.number == 1 else "object.revised"
    elif isinstance(source, SqlCatalogueAudit):
        if source.action not in {"PROMOTE", "HIDE", "RESTORE"}:
            return None
        revision = session.get(SqlObjectRevision, source.revision_id)
        action = {
            "PROMOTE": "library.promoted",
            "HIDE": "library.hidden",
            "RESTORE": "library.restored",
        }[source.action]
    elif isinstance(source, SqlResearchSummaryRevision):
        revision = session.scalar(
            select(SqlObjectRevision)
            .where(
                SqlObjectRevision.object_id == source.object_id,
                SqlObjectRevision.created_at <= source.created_at,
            )
            .order_by(SqlObjectRevision.number.desc())
            .limit(1)
        )
        action = "summary.created" if source.number == 1 else "summary.revised"
    elif isinstance(source, SqlPublicRelease):
        if source.publication_manifest_id is None:
            return None
        revision = session.get(SqlObjectRevision, source.object_revision_id)
        action = "research.published"
    elif isinstance(source, SqlResearchComment):
        revision = session.get(SqlObjectRevision, source.revision_id)
        action = "comment.created"
    elif isinstance(source, (SqlArtifactResearchLink, SqlResearchProgressUpdate)):
        revision = session.get(SqlObjectRevision, source.revision_id)
        action = (
            "evidence.attached"
            if isinstance(source, SqlArtifactResearchLink)
            else "progress.reported"
        )
    elif isinstance(source, SqlRelationAssertion):
        revision = session.get(SqlObjectRevision, source.source_revision_id)
        action = "relation.created"
    else:
        return None
    if revision is None or revision.ownership_scope_id is None:
        return None
    contribution_id = source.contribution_id
    envelope = session.get(SqlContributionEnvelope, contribution_id) if contribution_id else None
    if isinstance(source, SqlObjectRevision) and envelope and "catalogue" in envelope.operation:
        action = "library.admitted" if source.number == 1 else "library.revised"
    agent_id = envelope.external_agent_id if envelope else None
    if envelope and envelope.external_credential_id and agent_id is None:
        credential = session.get(SqlExternalAgentCredential, envelope.external_credential_id)
        agent_id = credential.agent_id if credential else None
    kind = SOURCE_KINDS[type(source)]
    return SqlResearchActivityEvent(
        id=uuid5(NAMESPACE_URL, f"polycolab:activity:{kind}:{source.id}"),
        source_kind=kind,
        source_id=source.id,
        contribution_id=contribution_id,
        actor_user_id=envelope.human_user_id
        if envelope
        else getattr(source, "created_by_user_id", None),
        agent_id=agent_id,
        sponsor_user_id=envelope.sponsor_user_id if envelope else None,
        ownership_scope_id=source.ownership_scope_id
        if isinstance(source, SqlRelationAssertion)
        else revision.ownership_scope_id,
        object_id=revision.object_id,
        revision_id=revision.id,
        previous_revision_id=revision.base_revision_id
        if isinstance(source, SqlObjectRevision)
        else None,
        action=action,
        occurred_at=source.created_at,
        reconstructed=reconstructed,
    )


def collect_history(session: Session, _: object) -> None:
    # after_flush has populated UUID/timestamp defaults. Adding an event here
    # participates in the same transaction and is flushed before commit.
    for source in list(session.new):
        if isinstance(source, (*SOURCES, SqlObjectVersionRelationship)):
            activity = from_source(session, source)
            if activity is not None:
                session.add(activity)


def install_history() -> None:
    if not event.contains(Session, "after_flush", collect_history):
        event.listen(Session, "after_flush", collect_history)


def backfill(session: Session, *, batch_size: int = 100) -> int:
    """Resumable insertion of evidenced history; existing live events win."""
    total = 0
    model: Any
    for model in SOURCES:
        after: UUID | None = None
        while True:
            query = select(model).order_by(model.id).limit(batch_size)
            if after:
                query = query.where(model.id > after)
            rows = list(session.scalars(query))
            if not rows:
                break
            for row in rows:
                activity = from_source(session, row, reconstructed=True)
                if (
                    activity is not None
                    and session.get(SqlResearchActivityEvent, activity.id) is None
                ):
                    # A savepoint keeps concurrent backfills/live writers harmless.
                    from sqlalchemy.exc import IntegrityError

                    try:
                        with session.begin_nested():
                            session.add(activity)
                            session.flush()
                        total += 1
                    except IntegrityError:
                        if session.get(SqlResearchActivityEvent, activity.id) is None:
                            raise
            after = rows[-1].id
            session.commit()
    return total


def main() -> None:
    """Rebuild only facts evidenced by immutable source records."""
    from polycolab.db.session import make_engine, make_session_factory
    from polycolab.platform.config import Settings

    settings = Settings()
    engine = make_engine(settings)
    with make_session_factory(engine)() as session:
        print(f"Reconstructed {backfill(session)} activity events")


def visible_query(access: ResearchAccess, scope: str) -> Any:
    query = (
        select(SqlResearchActivityEvent)
        .join(SqlObjectRevision, SqlObjectRevision.id == SqlResearchActivityEvent.revision_id)
        .join(SqlResearchScope, SqlResearchScope.id == SqlResearchActivityEvent.ownership_scope_id)
    )
    if scope == "member":
        access.require_user_id()
        query = query.join(SqlProject, SqlProject.id == SqlResearchScope.project_id).where(
            access.member_condition(), SqlProject.deleted_at.is_(None)
        )
    else:
        query = query.where(public_condition(SqlObjectRevision.id))
    # A public exact revision does not publish all discussion/evidence in its
    # private workspace. Only explicitly selected ancillary records are public.
    if scope != "member":
        public_container = or_(
            SqlResearchScope.project_id.is_(None),
            exists(
                select(SqlProject.id).where(
                    SqlProject.id == SqlResearchScope.project_id,
                    SqlProject.visibility == WorkspaceVisibility.PUBLIC,
                    SqlProject.deleted_at.is_(None),
                    SqlProject.archived_at.is_(None),
                )
            ),
        )
        for source_kind, _table, column in (
            ("ResearchComment", SqlPublicationComment, SqlPublicationComment.comment_id),
            ("ResearchProgressUpdate", SqlPublicationProgress, SqlPublicationProgress.progress_id),
            ("RelationAssertion", SqlPublicationRelation, SqlPublicationRelation.relation_id),
            (
                "ResearchSummaryRevision",
                SqlPublicationSummary,
                SqlPublicationSummary.summary_revision_id,
            ),
        ):
            query = query.where(
                or_(
                    SqlResearchActivityEvent.source_kind != source_kind,
                    public_container,
                    exists(select(column).where(column == SqlResearchActivityEvent.source_id)),
                )
            )
        query = query.where(
            or_(
                SqlResearchActivityEvent.source_kind != "ArtifactResearchLink",
                public_container,
                exists(
                    select(SqlArtifactResearchLink.id)
                    .join(
                        SqlPublicationArtifactMember,
                        SqlPublicationArtifactMember.artifact_id
                        == SqlArtifactResearchLink.artifact_id,
                    )
                    .join(
                        SqlPublicationManifest,
                        SqlPublicationManifest.id == SqlPublicationArtifactMember.manifest_id,
                    )
                    .join(
                        SqlPublicationRevision,
                        SqlPublicationRevision.manifest_id == SqlPublicationManifest.id,
                    )
                    .where(
                        SqlArtifactResearchLink.id == SqlResearchActivityEvent.source_id,
                        SqlPublicationRevision.revision_id == SqlArtifactResearchLink.revision_id,
                        SqlArtifactResearchLink.created_at <= SqlPublicationManifest.created_at,
                    )
                ),
            )
        )
        query = query.where(
            or_(
                SqlResearchActivityEvent.source_kind != "ResearchSummaryRevision",
                ~exists(
                    select(SqlSummarySourceRevision.summary_revision_id).where(
                        SqlSummarySourceRevision.summary_revision_id
                        == SqlResearchActivityEvent.source_id,
                        ~public_condition(SqlSummarySourceRevision.source_revision_id),
                    )
                ),
            )
        )
    endpoints_visible = []
    for endpoint in (
        SqlRelationAssertion.source_revision_id,
        SqlRelationAssertion.target_revision_id,
    ):
        visible = public_condition(endpoint)
        if scope == "member":
            candidate = aliased(SqlObjectRevision)
            visible = or_(
                visible,
                exists(
                    select(candidate.id).where(
                        candidate.id == endpoint,
                        candidate.ownership_scope_id == SqlResearchActivityEvent.ownership_scope_id,
                    )
                ),
            )
        endpoints_visible.append(visible)
    query = query.where(
        or_(
            SqlResearchActivityEvent.source_kind != "RelationAssertion",
            exists(
                select(SqlRelationAssertion.id).where(
                    SqlRelationAssertion.id == SqlResearchActivityEvent.source_id,
                    *endpoints_visible,
                )
            ),
        )
    )
    return query


def recent_public_submissions(access: ResearchAccess) -> Any:
    """Latest 500 visible events in active public workspaces, before UI filters."""
    latest = (
        visible_query(access, "public")
        .where(
            SqlResearchScope.project_id.in_(
                select(SqlProject.id).where(
                    SqlProject.visibility == WorkspaceVisibility.PUBLIC,
                    SqlProject.deleted_at.is_(None),
                    SqlProject.archived_at.is_(None),
                )
            )
        )
        .order_by(SqlResearchActivityEvent.occurred_at.desc(), SqlResearchActivityEvent.id.desc())
        .limit(500)
        .subquery()
    )
    return visible_query(access, "public").where(
        SqlResearchActivityEvent.id.in_(select(latest.c.id))
    )


if __name__ == "__main__":
    main()
