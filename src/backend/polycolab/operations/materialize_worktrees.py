"""Materialize one project's saved branches after draining runs and backing up storage."""

import argparse
from uuid import UUID

from polycolab.db.session import make_engine, make_session_factory
from polycolab.db.stores.repositories import SqlRepositoryStore
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.platform.config import get_settings
from polycolab.projects.git_storage import GitRepository
from polycolab.projects.worktree_service import WorktreeService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=UUID, required=True)
    parser.add_argument("--user", type=UUID, required=True, help="Existing project writer ID")
    args = parser.parse_args()
    settings = get_settings()
    if settings.project_repository_directory is None:
        parser.error("PROJECT_REPOSITORY_DIRECTORY is required")
    assert settings.project_repository_directory is not None
    engine = make_engine(settings)
    try:
        with make_session_factory(engine)() as db:
            service = WorktreeService(
                SqlAlchemyTransaction(db),
                SqlRepositoryStore(db),
                GitRepository(
                    settings.project_repository_directory,
                    args.project,
                    settings.project_repository_max_bytes,
                ),
                args.project,
                args.user,
            )
            with service.open():
                service.materialize()
                for task in service.store.tasks(args.project, False):
                    service.require_available(task)
            print(f"Worktrees verified for {args.project}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
