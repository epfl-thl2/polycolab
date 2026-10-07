"""Real PostgreSQL transaction and lock evidence for application stores."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine
from test_m0_postgresql import pg_schema as pg_schema

from polycolab.db.session import make_session_factory
from polycolab.db.transaction import make_transaction_factory
from polycolab.entities.enums import WorkspaceRole, WorkspaceVisibility
from polycolab.transaction import PersistenceConflict
from polycolab.workspaces.service import DomainConflict, change_membership_role, create_workspace


def test_owner_set_mutations_are_serialized_by_shared_transaction(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    factory = make_transaction_factory(make_session_factory(engine))
    with factory() as transaction:
        first = transaction.accounts.create_user(
            issuer="test", subject="first", email=None, display_name=None
        )
        second = transaction.accounts.create_user(
            issuer="test", subject="second", email=None, display_name=None
        )
        project = create_workspace(
            transaction,
            creator=first,
            name="Two owners",
            description=None,
            visibility=WorkspaceVisibility.PRIVATE,
            commit=False,
        )
        transaction.workspaces.add_membership(
            project_id=project.id, user_id=second.id, role=WorkspaceRole.OWNER, invited_by=first.id
        )
        transaction.commit()
    barrier = Barrier(2)

    def demote(index: int) -> bool:
        user = (first, second)[index]
        with factory() as transaction:
            barrier.wait(timeout=10)
            try:
                change_membership_role(
                    transaction,
                    project_id=project.id,
                    user_id=user.id,
                    role=WorkspaceRole.CONTRIBUTOR,
                )
            except DomainConflict:
                return False
            return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(demote, (0, 1)))
    assert sorted(results) == [False, True]
    with factory() as transaction:
        assert len(transaction.workspaces.owners(project.id)) == 1


def test_constraint_failure_rolls_back_new_workspace_and_user(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    factory = make_transaction_factory(make_session_factory(engine))
    import pytest

    with pytest.raises(PersistenceConflict), factory() as transaction:
        owner = transaction.accounts.create_user(
            issuer="test", subject="owner", email=None, display_name=None
        )
        project = create_workspace(
            transaction,
            creator=owner,
            name="Rolled back",
            description=None,
            visibility=WorkspaceVisibility.PRIVATE,
            commit=False,
        )
        transaction.workspaces.add_membership(
            project_id=project.id, user_id=owner.id, role=WorkspaceRole.OWNER, invited_by=None
        )
    with factory() as transaction:
        assert transaction.accounts.user(owner.id) is None
        assert transaction.workspaces.workspace(project.id) is None
        assert transaction.workspaces.membership(project.id, owner.id) is None
