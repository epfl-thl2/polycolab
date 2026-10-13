"""Account-wide credentials and project-bound external research runs."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from polycolab.access.actors import Actor, ActorOperation, external_agent_actor
from polycolab.access.authorization import (
    AuthorizationDenied,
    ProjectAction,
    lock_project_authorization,
    project_policy,
)
from polycolab.db.models import (
    SqlExternalAgentCredential,
    SqlExternalResearchRun,
    SqlObjectRevision,
    SqlResearchScope,
    SqlUser,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.accounts import IdentifiedUser
from polycolab.entities.enums import ProjectRole, ResearchScopeKind
from polycolab.entities.time import utc_now
from polycolab.model_gateway.credentials import (
    EncryptedCredential,
    KeyWrapper,
    decrypt_credential,
    encrypt_credential,
)
from polycolab.research.objects import ResearchNotFound

FIXED_RIGHTS = frozenset(
    {
        ActorOperation.CONTRIBUTION_CREATE,
        ActorOperation.CONTRIBUTION_EDIT,
        ActorOperation.PUBLIC_PARTICIPATION,
        ActorOperation.PROJECT_WRITE,
    }
)


class ExternalAgentInvalid(Exception):
    pass


class ExternalAgentConflict(Exception):
    pass


class ExternalAgentLimit(Exception):
    pass


class ExternalAgentUploadInterrupted(Exception):
    pass


def fixed_right_values() -> list[str]:
    return sorted(right.value for right in FIXED_RIGHTS)


def credential_rights(credential: SqlExternalAgentCredential) -> frozenset[ActorOperation]:
    try:
        values = credential.fixed_rights
        from polycolab.platform.project_history import credential_right

        rights = frozenset(ActorOperation(credential_right(value)) for value in values)
    except TypeError, ValueError:
        raise ExternalAgentInvalid from None
    if len(values) != len(rights) or rights != FIXED_RIGHTS:
        raise ExternalAgentInvalid
    return rights


@dataclass(frozen=True, slots=True)
class IssuedCredential:
    credential: SqlExternalAgentCredential
    secret: str


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def issue_credential(
    session: Session,
    *,
    sponsor: IdentifiedUser,
    name: str,
    ttl_seconds: int,
    max_requests: int,
    max_mutations: int,
    agent_id: UUID | None = None,
    allow_library_contributions: bool = False,
    allow_reviews: bool = False,
    wrapper: KeyWrapper | None = None,
) -> IssuedCredential:
    from polycolab.db.models import SqlExternalAgentIdentity

    if agent_id is None:
        identity = SqlExternalAgentIdentity(sponsor_user_id=sponsor.id, name=name)
        session.add(identity)
        session.flush()
        agent_id = identity.id
    else:
        existing_identity = session.get(SqlExternalAgentIdentity, agent_id)
        if existing_identity is None or existing_identity.sponsor_user_id != sponsor.id:
            raise AuthorizationDenied("agent identity is not owned by this account")
    credential_id = uuid4()
    secret = f"pca_{credential_id.hex}_{secrets.token_urlsafe(32)}"
    credential = SqlExternalAgentCredential(
        id=credential_id,
        project_id=None,
        scope_kind="ACCOUNT",
        agent_id=agent_id,
        allow_library_contributions=allow_library_contributions,
        allow_reviews=allow_reviews,
        sponsor_user_id=sponsor.id,
        name=name,
        token_digest=_digest(secret),
        fixed_rights=fixed_right_values(),
        expires_at=utc_now() + timedelta(seconds=ttl_seconds),
        max_requests=max_requests,
        max_mutations=max_mutations,
    )
    if wrapper is not None:
        encrypted = encrypt_credential(
            wrapper, context=key_secret_context(sponsor.id, credential_id), secret=secret
        )
        credential.encrypted_secret = encrypted.ciphertext
        credential.wrapped_data_key = encrypted.wrapped_key
        credential.encryption_key_version = encrypted.key_version
    session.add(credential)
    session.commit()
    session.refresh(credential)
    return IssuedCredential(credential, secret)


def key_secret_context(user_id: UUID, credential_id: UUID) -> bytes:
    return f"polycolab:agent-key:{user_id}:{credential_id}".encode("ascii")


def reveal_credential(
    session: Session, *, credential_id: UUID, user_id: UUID, wrapper: KeyWrapper
) -> str:
    credential = session.scalar(
        select(SqlExternalAgentCredential)
        .where(
            SqlExternalAgentCredential.id == credential_id,
            SqlExternalAgentCredential.sponsor_user_id == user_id,
        )
        .with_for_update()
    )
    if credential is None:
        raise ResearchNotFound
    if (
        credential.revoked_at is not None
        or not credential.encrypted_secret
        or not credential.wrapped_data_key
        or not credential.encryption_key_version
    ):
        raise ExternalAgentConflict
    return decrypt_credential(
        wrapper,
        context=key_secret_context(user_id, credential_id),
        encrypted=EncryptedCredential(
            credential.encrypted_secret,
            credential.wrapped_data_key,
            credential.encryption_key_version,
        ),
    )


def credential_from_secret(
    session: Session, secret: str, *, consume_request: bool = True
) -> SqlExternalAgentCredential:
    parts = secret.split("_", maxsplit=2)
    if len(parts) != 3 or parts[0] != "pca":
        raise ExternalAgentInvalid
    try:
        credential_id = UUID(hex=parts[1])
    except ValueError:
        raise ExternalAgentInvalid from None
    credential = session.scalar(
        select(SqlExternalAgentCredential)
        .where(SqlExternalAgentCredential.id == credential_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    now = utc_now()
    if (
        credential is None
        or credential.revoked_at is not None
        or _aware(credential.expires_at) <= now
        or not hmac.compare_digest(credential.token_digest, _digest(secret))
    ):
        raise ExternalAgentInvalid
    if credential.scope_kind == "PROJECT":
        raise ExternalAgentInvalid
    credential_rights(credential)
    if consume_request:
        if credential.request_count >= credential.max_requests:
            raise ExternalAgentLimit("credential_request_budget_exhausted")
        credential.request_count += 1
        session.commit()
    return credential


def revoke_credential(
    session: Session, *, credential_id: UUID, user_id: UUID
) -> SqlExternalAgentCredential:
    credential = session.scalar(
        select(SqlExternalAgentCredential)
        .where(
            SqlExternalAgentCredential.id == credential_id,
            SqlExternalAgentCredential.sponsor_user_id == user_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if credential is None:
        raise ResearchNotFound
    if credential.revoked_at is None:
        credential.revoked_at = utc_now()
        for run in session.scalars(
            select(SqlExternalResearchRun).where(
                SqlExternalResearchRun.credential_id == credential.id,
                SqlExternalResearchRun.status == "OPEN",
            )
        ):
            run.status = "REVOKED"
            run.closed_at = utc_now()
        session.commit()
    return credential


def create_run(
    session: Session,
    *,
    credential: SqlExternalAgentCredential,
    client_request_id: UUID,
    title: str | None,
    input_revision_ids: list[UUID],
    project_id: UUID,
) -> tuple[SqlExternalResearchRun, bool]:
    project_policy.require_scope(
        SqlAlchemyTransaction(session),
        project_id,
        credential.sponsor_user_id,
        ProjectAction.CREATE_RESEARCH,
    )
    existing = session.scalar(
        select(SqlExternalResearchRun).where(
            SqlExternalResearchRun.credential_id == credential.id,
            SqlExternalResearchRun.client_request_id == client_request_id,
        )
    )
    normalized = list(dict.fromkeys(input_revision_ids))
    if existing is not None:
        if (
            existing.project_id != project_id
            or existing.title != title
            or existing.input_revision_ids != [str(v) for v in normalized]
        ):
            from polycolab.research.contributions import ContributionConflict

            raise ContributionConflict
        return existing, True
    project_policy.require_scope(
        SqlAlchemyTransaction(session),
        project_id,
        credential.sponsor_user_id,
        ProjectAction.CREATE_RESEARCH,
    )
    for revision_id in normalized:
        readable_revision(session, credential, revision_id)
    locked = session.scalar(
        select(SqlExternalAgentCredential)
        .where(SqlExternalAgentCredential.id == credential.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None or locked.revoked_at is not None or _aware(locked.expires_at) <= utc_now():
        raise ExternalAgentInvalid
    if locked.mutation_count >= locked.max_mutations:
        raise ExternalAgentLimit("credential_mutation_budget_exhausted")
    run = SqlExternalResearchRun(
        credential_id=locked.id,
        project_id=project_id,
        sponsor_user_id=locked.sponsor_user_id,
        client_request_id=client_request_id,
        title=title,
        input_revision_ids=[str(value) for value in normalized],
    )
    locked.mutation_count += 1
    session.add(run)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        concurrent = session.scalar(
            select(SqlExternalResearchRun).where(
                SqlExternalResearchRun.credential_id == credential.id,
                SqlExternalResearchRun.client_request_id == client_request_id,
            )
        )
        if (
            concurrent is None
            or concurrent.project_id != project_id
            or concurrent.title != title
            or concurrent.input_revision_ids != [str(v) for v in normalized]
        ):
            raise ExternalAgentConflict from None
        return concurrent, True
    session.refresh(run)
    return run, False


def run_actor(
    session: Session,
    *,
    credential: SqlExternalAgentCredential,
    run_id: UUID,
    mutation: bool,
) -> tuple[SqlExternalResearchRun, Actor, SqlUser]:
    # Resolve ownership without a lock, then use project -> membership -> key -> run
    # consistently with membership removal and grant revocation.
    destination = session.scalar(
        select(SqlExternalResearchRun.project_id).where(
            SqlExternalResearchRun.id == run_id,
            SqlExternalResearchRun.credential_id == credential.id,
        )
    )
    if destination is None:
        raise ResearchNotFound
    project, membership = lock_project_authorization(
        SqlAlchemyTransaction(session), project_id=destination, user_id=credential.sponsor_user_id
    )
    current = session.scalar(
        select(SqlExternalAgentCredential)
        .where(SqlExternalAgentCredential.id == credential.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    run = session.scalar(
        select(SqlExternalResearchRun)
        .where(
            SqlExternalResearchRun.id == run_id,
            SqlExternalResearchRun.credential_id == credential.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if run is None:
        raise ResearchNotFound
    if (
        current is None
        or current.revoked_at is not None
        or _aware(current.expires_at) <= utc_now()
        or current.sponsor_user_id != run.sponsor_user_id
    ):
        raise ExternalAgentInvalid
    if project is None or project.deleted_at is not None or membership is None:
        raise ResearchNotFound
    if mutation and (
        project.archived_at is not None
        or membership.role not in {ProjectRole.OWNER, ProjectRole.CONTRIBUTOR}
    ):
        raise AuthorizationDenied
    if mutation and run.status != "OPEN":
        raise ExternalAgentConflict
    sponsor = session.get(SqlUser, run.sponsor_user_id)
    scope = session.scalar(
        select(SqlResearchScope).where(
            SqlResearchScope.project_id == run.project_id,
            SqlResearchScope.scope_kind == ResearchScopeKind.PROJECT,
        )
    )
    if sponsor is None or scope is None:
        raise ExternalAgentInvalid
    actor = external_agent_actor(
        sponsor_user_id=sponsor.id,
        credential_id=credential.id,
        run_id=run.id,
        project_id=run.project_id,
        ownership_scope_id=scope.id,
        operation_scope=credential_rights(current),
    )
    return run, actor, sponsor


def consume_mutation(session: Session, *, credential_id: UUID) -> None:
    """Consume one finite mutation only after an idempotency check created work."""

    credential = session.scalar(
        select(SqlExternalAgentCredential)
        .where(SqlExternalAgentCredential.id == credential_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if credential is None:
        raise ExternalAgentInvalid
    if credential.mutation_count >= credential.max_mutations:
        raise ExternalAgentLimit("credential_mutation_budget_exhausted")
    credential.mutation_count += 1


def close_run(
    session: Session,
    *,
    credential: SqlExternalAgentCredential,
    run_id: UUID,
    status: str,
    failure_code: str | None,
    commit: bool = True,
) -> SqlExternalResearchRun:
    run, _actor, _sponsor = run_actor(session, credential=credential, run_id=run_id, mutation=False)
    if status == "COMPLETED" and failure_code is not None:
        raise ExternalAgentConflict
    if status == "FAILED" and failure_code is None:
        raise ExternalAgentConflict
    if run.status != "OPEN":
        if run.status == status and run.failure_code == failure_code:
            return run
        raise ExternalAgentConflict
    run.status = status
    run.failure_code = failure_code
    run.closed_at = utc_now()
    consume_mutation(session, credential_id=credential.id)
    if commit:
        session.commit()
        session.refresh(run)
    else:
        session.flush()
    return run


def readable_revision(
    session: Session, credential: SqlExternalAgentCredential, revision_id: UUID
) -> SqlObjectRevision:
    """Public or shared member research, never a dedicated human note."""
    from polycolab.db.models import SqlObjectRevision, SqlResearchObject
    from polycolab.research.records import public_condition

    revision = session.scalar(select(SqlObjectRevision).where(SqlObjectRevision.id == revision_id))
    if revision is None:
        raise ResearchNotFound
    if session.scalar(
        select(SqlObjectRevision.id).where(
            SqlObjectRevision.id == revision_id, public_condition(SqlObjectRevision.id)
        )
    ):
        return revision
    project_policy.require_scope(
        SqlAlchemyTransaction(session),
        revision.project_id,
        credential.sponsor_user_id,
        ProjectAction.VIEW,
    )
    # Dedicated notes live outside generic research objects and are never projected here.
    obj = session.get(SqlResearchObject, revision.object_id)
    if obj is None:
        raise ResearchNotFound
    return revision
