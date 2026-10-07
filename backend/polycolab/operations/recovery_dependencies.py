"""Read-only restore checks for canonical Garage bytes and credential decryption.

Run only against a quiescent isolated restore. No provider calls, database writes,
object uploads/deletes, or credential migration are performed.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session, aliased, sessionmaker

from polycolab.artifacts.storage import ArtifactIntegrity, GarageStorage, garage_storage
from polycolab.db.models import (
    SqlArtifact,
    SqlContributionEnvelope,
    SqlCorrespondenceAssessment,
    SqlGatewayProfile,
    SqlObjectRevision,
    SqlProofSketchRevision,
    SqlPublicationManifest,
    SqlPublicationRevision,
    SqlPublicRelease,
    SqlResearchAttemptRevision,
    SqlResearchObject,
    SqlRevisionEndorsement,
    SqlStatementRevision,
)
from polycolab.db.models.relationships import SqlObjectVersionRelationship
from polycolab.db.session import make_engine, make_session_factory
from polycolab.entities.enums import (
    ArtifactState,
    ContributionActorKind,
    ProvenanceKind,
    ResearchObjectKind,
)
from polycolab.model_gateway.credentials import (
    EncryptedCredential,
    KeyWrapper,
    credential_context,
    decrypt_credential,
    wrapper_from_settings,
)
from polycolab.platform.config import get_settings
from polycolab.platform.outbox import canonical_digest


@dataclass(frozen=True)
class DependencyReport:
    status: Literal["VERIFIED", "LIMIT_REACHED", "DATABASE_FAILURE", "DEPENDENCY_FAILURE"]
    checked: int


@dataclass(frozen=True)
class ResearchIntegrityReport:
    status: Literal["VERIFIED", "LIMIT_REACHED", "DATABASE_FAILURE", "INTEGRITY_FAILURE"]
    checked: int
    sections: tuple[str, ...] = ()


def _read_only(session: Session) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SET TRANSACTION READ ONLY"))


def verify_artifacts(
    factory: sessionmaker[Session], storage: GarageStorage, *, max_items: int = 1000
) -> DependencyReport:
    """Verify committed bytes, not staging objects; end transactions before S3 I/O."""
    if type(max_items) is not int or not 1 <= max_items <= 1_000_000:
        raise ValueError("invalid item bound")
    checked = 0
    cursor: UUID | None = None
    while True:
        try:
            with factory() as session:
                _read_only(session)
                query = select(SqlArtifact).where(SqlArtifact.state == ArtifactState.COMMITTED)
                if cursor is not None:
                    query = query.where(SqlArtifact.id > cursor)
                rows = list(session.scalars(query.order_by(SqlArtifact.id).limit(100)))
            if not rows:
                return DependencyReport("VERIFIED", checked)
        except Exception:
            return DependencyReport("DATABASE_FAILURE", checked)
        for row in rows:
            if checked == max_items:
                return DependencyReport("LIMIT_REACHED", checked)
            try:
                storage.get_verified(
                    row.storage_key, ArtifactIntegrity(row.sha256, row.byte_length)
                )
            except Exception:
                return DependencyReport("DEPENDENCY_FAILURE", checked)
            checked += 1
            cursor = row.id


def verify_credentials(
    factory: sessionmaker[Session], wrapper: KeyWrapper, *, max_items: int = 1000
) -> DependencyReport:
    """Check all retained envelopes, including deleted profiles, without retaining plaintext."""
    if type(max_items) is not int or not 1 <= max_items <= 1_000_000:
        raise ValueError("invalid item bound")
    checked = 0
    cursor: UUID | None = None
    while True:
        try:
            with factory() as session:
                _read_only(session)
                query = select(SqlGatewayProfile)
                if cursor is not None:
                    query = query.where(SqlGatewayProfile.id > cursor)
                rows = list(session.scalars(query.order_by(SqlGatewayProfile.id).limit(100)))
            if not rows:
                return DependencyReport("VERIFIED", checked)
        except Exception:
            return DependencyReport("DATABASE_FAILURE", checked)
        for row in rows:
            if checked == max_items:
                return DependencyReport("LIMIT_REACHED", checked)
            try:
                decrypt_credential(
                    wrapper,
                    context=credential_context(user_id=row.user_id, profile_id=row.id),
                    encrypted=EncryptedCredential(
                        row.encrypted_credential, row.wrapped_data_key, row.encryption_key_version
                    ),
                )
            except Exception:
                return DependencyReport("DEPENDENCY_FAILURE", checked)
            checked += 1
            cursor = row.id


def _provenance_is_coherent(
    provenance: ProvenanceKind,
    created_by_user_id: UUID,
    envelope: SqlContributionEnvelope,
    ownership_scope_id: UUID,
) -> bool:
    if envelope.ownership_scope_id != ownership_scope_id:
        return False
    if provenance is ProvenanceKind.HUMAN_DIRECT:
        return (
            envelope.actor_kind is ContributionActorKind.HUMAN
            and envelope.human_user_id == created_by_user_id
        )
    return (
        provenance in {ProvenanceKind.AGENT_DIRECT, ProvenanceKind.AGENT_PROPOSAL}
        and envelope.actor_kind is ContributionActorKind.AGENT
        and envelope.sponsor_user_id == created_by_user_id
    )


def verify_research_integrity(
    factory: sessionmaker[Session], *, max_items: int = 100_000
) -> ResearchIntegrityReport:
    """Interpret restored research links without returning any canonical content."""

    if type(max_items) is not int or not 1 <= max_items <= 1_000_000:
        raise ValueError("invalid item bound")
    models = (
        SqlResearchObject,
        SqlObjectRevision,
        SqlObjectVersionRelationship,
        SqlPublicRelease,
        SqlPublicationManifest,
        SqlPublicationRevision,
        SqlRevisionEndorsement,
        SqlCorrespondenceAssessment,
    )
    try:
        with factory() as session:
            _read_only(session)
            counts = [
                int(session.scalar(select(func.count()).select_from(model)) or 0)
                for model in models
            ]
            total = sum(counts)
            if total > max_items:
                # This verifier is all-or-nothing: do not imply that a prefix was
                # accepted when cross-table invariants were not evaluated.
                return ResearchIntegrityReport("LIMIT_REACHED", 0)

            failures: set[str] = set()
            latest = (
                select(
                    SqlObjectRevision.object_id,
                    func.max(SqlObjectRevision.number).label("number"),
                )
                .group_by(SqlObjectRevision.object_id)
                .subquery()
            )
            current = aliased(SqlObjectRevision)
            for obj, current_revision, latest_number in session.execute(
                select(SqlResearchObject, current, latest.c.number)
                .outerjoin(current, current.id == SqlResearchObject.current_revision_id)
                .outerjoin(latest, latest.c.object_id == SqlResearchObject.id)
                .execution_options(yield_per=100)
            ):
                if (
                    current_revision is None
                    or current_revision.object_id != obj.id
                    or latest_number is None
                    or current_revision.number != latest_number
                ):
                    failures.add("revision_heads")

            base = aliased(SqlObjectRevision)
            for revision, base_revision in session.execute(
                select(SqlObjectRevision, base)
                .outerjoin(base, base.id == SqlObjectRevision.base_revision_id)
                .execution_options(yield_per=100)
            ):
                if revision.number == 1:
                    valid = revision.base_revision_id is None
                else:
                    valid = (
                        base_revision is not None
                        and base_revision.object_id == revision.object_id
                        and base_revision.number == revision.number - 1
                    )
                if not valid:
                    failures.add("revision_chains")

            structures: dict[UUID, dict[str, list[SqlObjectRevision]]] = defaultdict(
                lambda: defaultdict(list)
            )
            statement_ids = set(session.scalars(select(SqlStatementRevision.revision_id)))
            attempt_object_ids = set(
                session.scalars(
                    select(SqlResearchObject.id).where(
                        SqlResearchObject.kind == ResearchObjectKind.ATTEMPT
                    )
                )
            )
            source = aliased(SqlObjectRevision)
            target = aliased(SqlObjectRevision)
            for relation, source_revision, target_revision in session.execute(
                select(SqlObjectVersionRelationship, source, target)
                .outerjoin(
                    source,
                    source.id
                    == func.coalesce(
                        SqlObjectVersionRelationship.source_object_version_id,
                        SqlObjectVersionRelationship.first_object_version_id,
                    ),
                )
                .outerjoin(
                    target,
                    target.id
                    == func.coalesce(
                        SqlObjectVersionRelationship.target_object_version_id,
                        SqlObjectVersionRelationship.second_object_version_id,
                    ),
                )
                .execution_options(yield_per=100)
            ):
                if source_revision is None or target_revision is None:
                    failures.add("relations")
                    continue
                if relation.direction == "BIDIRECTIONAL":
                    valid = (
                        relation.binding == "DECLARATION"
                        and relation.relationship_type == "EQUIVALENT_TO"
                        and relation.source_object_version_id is None
                        and relation.target_object_version_id is None
                        and relation.first_object_version_id == source_revision.id
                        and relation.second_object_version_id == target_revision.id
                        and source_revision.id <= target_revision.id
                    )
                else:
                    valid = (
                        relation.direction == "UNIDIRECTIONAL"
                        and relation.first_object_version_id is None
                        and relation.second_object_version_id is None
                        and source_revision.ownership_scope_id == relation.ownership_scope_id
                    )
                    if relation.binding == "STRUCTURAL":
                        structures[source_revision.id][relation.relationship_type].append(
                            target_revision
                        )
                        valid = valid and (
                            relation.contribution_id == source_revision.contribution_id
                            and relation.created_by_user_id == source_revision.created_by_user_id
                            and relation.provenance_kind == source_revision.provenance_kind
                            and relation.created_at == source_revision.created_at
                        )
                        if relation.relationship_type in {"ATTACHMENT", "CONCLUSION", "PREMISE"}:
                            valid = valid and target_revision.id in statement_ids
                        if relation.relationship_type == "TARGET":
                            valid = valid and target_revision.object_id not in attempt_object_ids
                if not valid:
                    failures.add("relations")

            # Check complete sets, not just surviving edges: an absent conclusion
            # or target cannot be detected by iterating relationship rows alone.
            proof_ids = set(session.scalars(select(SqlProofSketchRevision.revision_id)))
            attempt_ids = set(session.scalars(select(SqlResearchAttemptRevision.revision_id)))
            for version_id in proof_ids | attempt_ids | structures.keys():
                pins = structures.get(version_id, {})
                conclusions = pins.get("CONCLUSION", [])
                premises = pins.get("PREMISE", [])
                targets = pins.get("TARGET", [])
                results = pins.get("RESULT", [])
                if version_id in proof_ids:
                    attachments = {item.id for item in pins.get("ATTACHMENT", [])}
                    if (
                        len(conclusions) != 1
                        or any(item.id not in attachments for item in conclusions + premises)
                        or {item.id for item in conclusions} & {item.id for item in premises}
                    ):
                        failures.add("relations")
                elif conclusions or premises:
                    failures.add("relations")
                if version_id in attempt_ids:
                    if len(targets) != 1 or len(results) > 1:
                        failures.add("relations")
                    elif results and (
                        results[0].object_id != targets[0].object_id
                        or results[0].number <= targets[0].number
                    ):
                        failures.add("relations")
                elif targets or results or pins.get("EVIDENCE"):
                    failures.add("relations")

            for entity_model in (
                SqlResearchObject,
                SqlObjectRevision,
                SqlObjectVersionRelationship,
            ):
                for entity, envelope in session.execute(
                    select(entity_model, SqlContributionEnvelope)
                    .outerjoin(
                        SqlContributionEnvelope,
                        SqlContributionEnvelope.id == entity_model.contribution_id,
                    )
                    .execution_options(yield_per=100)
                ):
                    if envelope is None or not _provenance_is_coherent(
                        entity.provenance_kind,
                        entity.created_by_user_id,
                        envelope,
                        entity.ownership_scope_id,
                    ):
                        failures.add("provenance")

            membership = aliased(SqlPublicationRevision)
            for release, revision, manifest, member in session.execute(
                select(SqlPublicRelease, SqlObjectRevision, SqlPublicationManifest, membership)
                .outerjoin(
                    SqlObjectRevision, SqlObjectRevision.id == SqlPublicRelease.object_revision_id
                )
                .outerjoin(
                    SqlPublicationManifest,
                    SqlPublicationManifest.id == SqlPublicRelease.publication_manifest_id,
                )
                .outerjoin(
                    membership,
                    and_(
                        membership.manifest_id == SqlPublicRelease.publication_manifest_id,
                        membership.revision_id == SqlPublicRelease.object_revision_id,
                    ),
                )
                .execution_options(yield_per=100)
            ):
                fields = release.public_fields
                valid = (
                    revision is not None
                    and release.ownership_scope_id == revision.ownership_scope_id
                    and release.projection_version in {1, 2, 3, 4, 5}
                    and isinstance(fields, dict)
                    and canonical_digest(fields) == release.public_fields_digest
                    and fields.get("object_id") == str(revision.object_id)
                    and fields.get("revision_id") == str(revision.id)
                )
                if release.publication_manifest_id is not None:
                    valid = (
                        valid
                        and manifest is not None
                        and member is not None
                        and manifest.contribution_id == release.contribution_id
                    )
                if not valid:
                    failures.add("public_releases")

            missing_release = session.scalar(
                select(SqlPublicationRevision.revision_id)
                .outerjoin(
                    SqlPublicRelease,
                    SqlPublicRelease.object_revision_id == SqlPublicationRevision.revision_id,
                )
                .where(SqlPublicRelease.id.is_(None))
                .limit(1)
            )
            if missing_release is not None:
                failures.add("publication_membership")

            missing_member = session.scalar(
                select(SqlPublicationManifest.id)
                .outerjoin(
                    SqlPublicationRevision,
                    SqlPublicationRevision.manifest_id == SqlPublicationManifest.id,
                )
                .where(SqlPublicationRevision.manifest_id.is_(None))
                .limit(1)
            )
            if missing_member is not None:
                failures.add("publication_membership")

            for manifest, envelope in session.execute(
                select(SqlPublicationManifest, SqlContributionEnvelope)
                .outerjoin(
                    SqlContributionEnvelope,
                    SqlContributionEnvelope.id == SqlPublicationManifest.contribution_id,
                )
                .execution_options(yield_per=100)
            ):
                if (
                    envelope is None
                    or envelope.actor_kind is not ContributionActorKind.HUMAN
                    or envelope.human_user_id != manifest.created_by_user_id
                    or envelope.ownership_scope_id != manifest.ownership_scope_id
                    or envelope.operation != "publication.confirm"
                ):
                    failures.add("publication_attribution")

            for assurance_model in (SqlRevisionEndorsement, SqlCorrespondenceAssessment):
                for row, envelope in session.execute(
                    select(assurance_model, SqlContributionEnvelope)
                    .outerjoin(
                        SqlContributionEnvelope,
                        SqlContributionEnvelope.id == assurance_model.contribution_id,
                    )
                    .execution_options(yield_per=100)
                ):
                    if (
                        envelope is None
                        or envelope.actor_kind is not ContributionActorKind.HUMAN
                        or envelope.human_user_id != row.created_by_user_id
                    ):
                        failures.add("assurance_attribution")
            if failures:
                return ResearchIntegrityReport("INTEGRITY_FAILURE", total, tuple(sorted(failures)))
            return ResearchIntegrityReport("VERIFIED", total)
    except Exception:
        return ResearchIntegrityReport("DATABASE_FAILURE", 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("research", "artifacts", "credentials"))
    parser.add_argument("--isolated-restore", action="store_true", required=True)
    parser.add_argument("--max-items", type=int, default=1000)
    args = parser.parse_args(argv)
    if not 1 <= args.max_items <= 1_000_000:
        parser.error("--max-items must be 1-1000000")
    try:
        settings = get_settings()
        engine = make_engine(settings)
        try:
            factory = make_session_factory(engine)
            report: DependencyReport | ResearchIntegrityReport
            if args.kind == "research":
                report = verify_research_integrity(factory, max_items=args.max_items)
            elif args.kind == "artifacts":
                if (
                    settings.artifact_s3_endpoint is None
                    or settings.artifact_s3_bucket is None
                    or settings.artifact_s3_region is None
                    or settings.artifact_s3_access_key is None
                    or settings.artifact_s3_secret_key is None
                ):
                    raise ValueError("storage configuration required")
                storage = garage_storage(
                    endpoint=str(settings.artifact_s3_endpoint),
                    bucket=settings.artifact_s3_bucket,
                    region=settings.artifact_s3_region,
                    access_key=settings.artifact_s3_access_key.get_secret_value(),
                    secret_key=settings.artifact_s3_secret_key.get_secret_value(),
                )
                try:
                    report = verify_artifacts(factory, storage, max_items=args.max_items)
                finally:
                    storage.client.close()
            else:
                wrapper = wrapper_from_settings(settings)
                try:
                    report = verify_credentials(factory, wrapper, max_items=args.max_items)
                finally:
                    close = getattr(wrapper, "close", None)
                    if close is not None:
                        close()
        finally:
            engine.dispose()
    except Exception:
        print(json.dumps({"status": "CONFIGURATION_OR_RUNTIME_FAILURE"}))
        return 1
    print(json.dumps(asdict(report), sort_keys=True))
    return 0 if report.status == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
