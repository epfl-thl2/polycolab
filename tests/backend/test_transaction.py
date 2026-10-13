"""Application transactions and materialized entities across SQL stores."""

from collections.abc import Iterator
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import cast
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from polycolab.access.authorization import ProjectAction, project_policy
from polycolab.db.base import Base
from polycolab.db.models import SqlInvitation, SqlMembership, SqlProject, SqlResearchScope
from polycolab.db.session import make_engine, make_session_factory
from polycolab.db.transaction import make_transaction_factory
from polycolab.entities.accounts import User
from polycolab.entities.enums import ProjectRole, ProjectVisibility
from polycolab.entities.projects import Membership
from polycolab.entities.time import utc_now
from polycolab.platform.config import Settings
from polycolab.projects.service import DomainConflict, change_membership_role, create_project
from polycolab.transaction import PersistenceConflict, Transaction, TransactionFactory


@pytest.fixture(params=["memory", "file"])
def factory(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[TransactionFactory]:
    database = ":memory:" if request.param == "memory" else str(tmp_path / "transaction.db")
    engine = make_engine(Settings(database_url=f"sqlite+pysqlite:///{database}"))
    Base.metadata.create_all(engine)
    yield make_transaction_factory(make_session_factory(engine))
    engine.dispose()


def create_owner(factory: TransactionFactory) -> User:
    with factory() as transaction:
        owner = transaction.accounts.create_user(
            issuer="test", subject="owner", email=None, display_name="Owner"
        )
        transaction.commit()
    return owner


@pytest.mark.parametrize("completion", ["uncommitted", "rollback", "exception", "commit"])
def test_first_write_in_savepoint_obeys_outer_transaction(
    factory: TransactionFactory, completion: str
) -> None:
    user_id = uuid4()
    try:
        with factory() as transaction:
            with transaction.savepoint():
                user = transaction.accounts.create_user(
                    issuer="test", subject="savepoint-first", email=None, display_name=None
                )
                user_id = user.id
            if completion == "commit":
                transaction.commit()
            elif completion == "rollback":
                transaction.rollback()
            elif completion == "exception":
                raise RuntimeError("abort outer transaction")
    except RuntimeError:
        assert completion == "exception"
    with factory() as check:
        assert (check.accounts.user(user_id) is not None) == (completion == "commit")


def test_uncommitted_work_rolls_back_across_stores(factory: TransactionFactory) -> None:
    with factory() as transaction:
        owner = transaction.accounts.create_user(
            issuer="test", subject="owner", email=None, display_name="Owner"
        )
        project = create_project(
            transaction,
            creator=owner,
            name="Uncommitted",
            description=None,
            visibility=ProjectVisibility.PRIVATE,
            commit=False,
        )
        assert transaction.projects.membership(project.id, owner.id) is not None
    with factory() as check:
        assert check.accounts.user(owner.id) is None
        assert check.projects.project(project.id) is None
        assert check.projects.membership(project.id, owner.id) is None


def test_explicit_commit_materializes_multi_table_project(factory: TransactionFactory) -> None:
    owner = create_owner(factory)
    with factory() as transaction:
        project = create_project(
            transaction,
            creator=owner,
            name="Project",
            description=None,
            visibility=ProjectVisibility.PRIVATE,
        )
        scope = project_policy.require_scope(transaction, project.id, owner.id, ProjectAction.VIEW)
        visible = transaction.projects.list_visible(
            user_id=owner.id, members_only=True, query=None, after=None, limit=10
        )
    assert scope.project == project
    assert visible[0].project == project
    assert visible[0].membership is not None
    assert visible[0].membership.role is ProjectRole.OWNER
    assert visible[0].project.description is None
    assert not hasattr(scope.project, "_sa_instance_state")
    assert not hasattr(scope.membership, "_sa_instance_state")
    with pytest.raises(FrozenInstanceError):
        scope.project.name = "Mutated outside the store"  # type: ignore[misc]
    with factory() as check:
        assert check.projects.project(project.id) == project


def test_constraint_failure_rolls_back_whole_operation(factory: TransactionFactory) -> None:
    owner = create_owner(factory)
    project_id = uuid4()
    with pytest.raises(PersistenceConflict), factory() as transaction:
        project = create_project(
            transaction,
            creator=owner,
            name="Conflict",
            description=None,
            visibility=ProjectVisibility.PRIVATE,
            commit=False,
        )
        project_id = project.id
        transaction.projects.add_membership(
            project_id=project_id, user_id=owner.id, role=ProjectRole.OWNER, invited_by=None
        )
        transaction.commit()
    with factory() as check:
        assert check.projects.project(project_id) is None
        assert check.projects.membership(project_id, owner.id) is None
        assert check.accounts.user(owner.id) == owner


def test_savepoint_failure_preserves_outer_operation(factory: TransactionFactory) -> None:
    owner = create_owner(factory)
    with factory() as transaction:
        project = create_project(
            transaction,
            creator=owner,
            name="Outer transaction",
            description=None,
            visibility=ProjectVisibility.PRIVATE,
            commit=False,
        )
        with pytest.raises(PersistenceConflict), transaction.savepoint():
            transaction.projects.add_membership(
                project_id=project.id, user_id=owner.id, role=ProjectRole.OWNER, invited_by=None
            )
        assert transaction.projects.project(project.id) is not None
        transaction.commit()
    with factory() as check:
        assert check.projects.project(project.id) is not None
        assert len(check.projects.owners(project.id)) == 1


def test_last_owner_policy_uses_application_state_without_database() -> None:
    project_id, user_id = uuid4(), uuid4()
    owner = Membership(uuid4(), project_id, user_id, ProjectRole.OWNER, None, utc_now(), utc_now())
    transaction = Mock()
    transaction.projects.membership.return_value = owner
    transaction.projects.owners.return_value = (owner,)
    with pytest.raises(DomainConflict):
        change_membership_role(
            cast(Transaction, transaction),
            project_id=project_id,
            user_id=user_id,
            role=ProjectRole.READ_ONLY,
        )
    transaction.projects.project.assert_called_once_with(project_id, lock=True)
    transaction.projects.membership.assert_called_once_with(project_id, user_id, lock=True)
    transaction.projects.change_role.assert_not_called()
    transaction.commit.assert_not_called()


def test_no_implicit_store_commit_and_invitation_projection() -> None:
    """Observe rows through SQL only in this adapter-level test."""
    engine = make_engine(Settings(database_url="sqlite+pysqlite:///:memory:"))
    Base.metadata.create_all(engine)
    factory = make_transaction_factory(make_session_factory(engine))
    owner = create_owner(factory)
    try:
        with factory() as transaction:
            project = create_project(
                transaction,
                creator=owner,
                name="Private",
                description=None,
                visibility=ProjectVisibility.PRIVATE,
                commit=False,
            )
            invitation = transaction.projects.create_invitation(
                project_id=project.id,
                email="reader@example.test",
                role=ProjectRole.READ_ONLY,
                token_digest="a" * 64,
                invited_by=owner.id,
                expires_at=utc_now(),
            )
            assert not hasattr(invitation, "token_digest")
            transaction.rollback()
        with Session(engine) as session:
            for model in (SqlProject, SqlMembership, SqlResearchScope, SqlInvitation):
                assert session.scalar(select(func.count()).select_from(model)) == 0
    finally:
        engine.dispose()
