"""Real PostgreSQL transaction and lock evidence for application stores."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine

from polycolab.db.session import make_session_factory
from polycolab.db.transaction import make_transaction_factory
from polycolab.entities.enums import ProjectRole, ProjectVisibility
from polycolab.projects.service import DomainConflict, change_membership_role, create_project
from polycolab.transaction import PersistenceConflict


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
        project = create_project(
            transaction,
            creator=first,
            name="Two owners",
            description=None,
            visibility=ProjectVisibility.PRIVATE,
            commit=False,
        )
        transaction.projects.add_membership(
            project_id=project.id, user_id=second.id, role=ProjectRole.OWNER, invited_by=first.id
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
                    role=ProjectRole.CONTRIBUTOR,
                )
            except DomainConflict:
                return False
            return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(demote, (0, 1)))
    assert sorted(results) == [False, True]
    with factory() as transaction:
        assert len(transaction.projects.owners(project.id)) == 1


def test_constraint_failure_rolls_back_new_project_and_user(
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
        project = create_project(
            transaction,
            creator=owner,
            name="Rolled back",
            description=None,
            visibility=ProjectVisibility.PRIVATE,
            commit=False,
        )
        transaction.projects.add_membership(
            project_id=project.id, user_id=owner.id, role=ProjectRole.OWNER, invited_by=None
        )
    with factory() as transaction:
        assert transaction.accounts.user(owner.id) is None
        assert transaction.projects.project(project.id) is None
        assert transaction.projects.membership(project.id, owner.id) is None
