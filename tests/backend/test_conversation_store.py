"""Materialized conversation stores and session authority policy."""

from dataclasses import replace
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from polycolab.access.authorization import AuthorizationDenied, ProjectNotFound
from polycolab.agents.conversations import create_agent_conversation
from polycolab.conversations.service import (
    ConversationStateError,
    children,
    require_interrupt,
    require_read,
    require_submit,
    set_sharing,
)
from polycolab.db.models import SqlMembership, SqlProject, SqlUser
from polycolab.db.models.agents import SqlConversation
from polycolab.db.stores.conversations import SqlConversationStore
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.conversation import (
    AgentAuthor,
    ConversationHierarchy,
    ConversationSharing,
    ConversationStatus,
    MessageData,
    MessageRole,
)
from polycolab.entities.enums import PlatformAgentKind, ProjectRole
from polycolab.entities.time import utc_now


def setup(client: TestClient) -> tuple[Any, Any, Any, Any, Any]:
    db = cast(Any, client.app).state.session_factory()
    owner, contributor, reader, other_owner = [
        SqlUser(issuer="sessions", subject=str(uuid4())) for _ in range(4)
    ]
    db.add_all([owner, contributor, reader, other_owner])
    db.flush()
    project = SqlProject(name="Shared", created_by_user_id=owner.id)
    db.add(project)
    db.flush()
    for user, role in (
        (owner, ProjectRole.OWNER),
        (contributor, ProjectRole.EDITOR),
        (reader, ProjectRole.VIEWER),
        (other_owner, ProjectRole.OWNER),
    ):
        db.add(SqlMembership(project_id=project.id, user_id=user.id, role=role))
    db.commit()
    row = create_agent_conversation(
        db,
        project_id=project.id,
        created_by_user_id=owner.id,
        agent_kind=PlatformAgentKind.RESEARCHER,
    )
    return db, row, owner, contributor, (reader, other_owner)


def test_sharing_and_interrupt_authority_uses_sender_and_current_membership(
    client: TestClient,
) -> None:
    db, row, owner, contributor, (reader, other_owner) = setup(client)
    try:
        transaction = SqlAlchemyTransaction(db)
        for stranger in (contributor, reader, other_owner):
            with pytest.raises(ProjectNotFound):
                require_read(transaction, row.id, stranger.id)
        set_sharing(transaction, row.id, owner.id, ConversationSharing.MEMBERS_CAN_VIEW)
        assert require_read(transaction, row.id, reader.id).owner_id == owner.id
        with pytest.raises(AuthorizationDenied):
            require_submit(transaction, row.id, contributor.id)
        set_sharing(transaction, row.id, owner.id, ConversationSharing.MEMBERS_CAN_PARTICIPATE)
        assert require_submit(transaction, row.id, contributor.id).id == row.id
        with pytest.raises(AuthorizationDenied):
            require_submit(transaction, row.id, reader.id)
        with pytest.raises(AuthorizationDenied):
            set_sharing(transaction, row.id, other_owner.id, ConversationSharing.PRIVATE)
        require_interrupt(transaction, row.id, contributor.id, requested_by_user_id=contributor.id)
        require_interrupt(transaction, row.id, owner.id, requested_by_user_id=contributor.id)
        with pytest.raises(AuthorizationDenied):
            require_interrupt(
                transaction, row.id, other_owner.id, requested_by_user_id=contributor.id
            )
        db.execute(
            delete(SqlMembership).where(
                SqlMembership.project_id == row.project_id,
                SqlMembership.user_id == contributor.id,
            )
        )
        db.commit()
        with pytest.raises((ProjectNotFound, AuthorizationDenied)):
            require_submit(transaction, row.id, contributor.id)
        assert transaction.conversations.list_accessible(contributor.id) == []
    finally:
        db.close()


def test_child_relationships_and_transaction_materialization(
    client: TestClient,
) -> None:
    db, row, owner, contributor, _ = setup(client)
    try:
        store = SqlConversationStore(db)
        root = store.conversation(row.id)
        assert root is not None
        set_sharing(
            SqlAlchemyTransaction(db),
            row.id,
            owner.id,
            ConversationSharing.MEMBERS_CAN_VIEW,
        )
        child = replace(
            root,
            id=uuid4(),
            hierarchy=ConversationHierarchy(root_id=root.id, parent_id=root.id),
        )
        saved = store.create(child)
        db.commit()
        assert saved.sharing is ConversationSharing.PRIVATE
        assert children(SqlAlchemyTransaction(db), root.id, contributor.id) == []
        assert [value.id for value in children(SqlAlchemyTransaction(db), root.id, owner.id)] == [
            child.id
        ]
        with pytest.raises(ValueError, match="parent's project and root"):
            store.create(replace(child, id=uuid4(), project_id=uuid4()))
        with pytest.raises(ValueError, match="parent's project and root"):
            store.create(
                replace(
                    child,
                    id=uuid4(),
                    hierarchy=ConversationHierarchy(root_id=uuid4(), parent_id=root.id),
                )
            )
        transient = store.create(replace(child, id=uuid4()))
        db.rollback()
        assert store.conversation(transient.id) is None
        db.close()
        assert saved.configuration is not None
        assert root.configuration is not None
        assert saved.configuration.agent_version_id == root.configuration.agent_version_id
        assert saved.hierarchy.root_id == root.id
    finally:
        db.close()


def test_legacy_history_is_read_only_but_owner_can_change_metadata(
    client: TestClient,
) -> None:
    db, _, owner, contributor, _ = setup(client)
    try:
        row = SqlConversation(
            created_by_user_id=owner.id,
            origin="legacy_direct",
            project_id=None,
            title="Imported history",
        )
        db.add(row)
        db.commit()
        transaction = SqlAlchemyTransaction(db)
        value = require_read(transaction, row.id, owner.id)
        assert value.project_id is None
        assert value.configuration is None
        with pytest.raises(ProjectNotFound):
            require_read(transaction, row.id, contributor.id)
        with pytest.raises(ConversationStateError):
            require_submit(transaction, row.id, owner.id)
        with pytest.raises(ConversationStateError):
            set_sharing(transaction, row.id, owner.id, ConversationSharing.MEMBERS_CAN_VIEW)
        with pytest.raises(ValueError, match="only agent conversations"):
            transaction.conversations.append_item(
                row.id,
                item_id=uuid4(),
                author=AgentAuthor(None),
                data=MessageData(MessageRole.ASSISTANT, "No inference"),
                created_at=utc_now(),
            )
        archived = transaction.conversations.set_metadata(
            row.id,
            title="Read-only notes",
            status=ConversationStatus.ARCHIVED,
            updated_at=utc_now(),
        )
        transaction.commit()
        assert archived.title == "Read-only notes"
        assert archived.archived_at is not None
    finally:
        db.close()
