"""Static dependency checks for the capability-oriented backend package."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

from polycolab.db import models
from polycolab.db.base import Base

PACKAGE = Path(__file__).resolve().parents[2] / "src/backend" / "polycolab"


def test_mapped_classes_and_exports_keep_sql_prefix() -> None:
    modules = [models]
    modules.extend(
        importlib.import_module(f"polycolab.db.models.{path.stem}")
        for path in (PACKAGE / "db" / "models").glob("*.py")
        if path.stem != "__init__"
    )
    mapped_classes = {mapper.class_ for mapper in Base.registry.mappers}
    assert mapped_classes
    assert all(model.__name__.startswith("Sql") for model in mapped_classes)
    for module in modules:
        for name, value in vars(module).items():
            if isinstance(value, type) and value in mapped_classes:
                assert name.startswith("Sql"), f"{module.__name__}.{name} hides a mapped class"
        for name in getattr(module, "__all__", ()):
            assert hasattr(module, name), f"{module.__name__} exports missing {name}"


def test_mapped_class_imports_keep_sql_prefix() -> None:
    mapped_names = {mapper.class_.__name__ for mapper in Base.registry.mappers}
    root = PACKAGE.parents[2]
    paths = list(PACKAGE.rglob("*.py")) + list((root / "tests").rglob("*.py"))
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in mapped_names:
                        assert (alias.asname or alias.name).startswith("Sql"), (
                            f"{path}:{node.lineno} hides mapped class {alias.name}"
                        )


def imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
    return modules


def test_application_entities_do_not_depend_on_adapters() -> None:
    for path in (PACKAGE / "entities").rglob("*.py"):
        for module in imported_modules(path):
            assert not module.startswith(("sqlalchemy", "fastapi", "polycolab.db"))
            if module.startswith("polycolab."):
                assert module.startswith("polycolab.entities"), f"{path.name} imports {module}"


def test_database_models_depend_only_on_persistence_primitives_and_application_values() -> None:
    for path in (PACKAGE / "db" / "models").glob("*.py"):
        for module in imported_modules(path):
            if module.startswith("polycolab."):
                assert (
                    module.startswith(("polycolab.db.models", "polycolab.entities"))
                    or module == "polycolab.db.base"
                ), f"{path.name} imports {module}"


def test_project_service_and_store_interfaces_do_not_import_database_adapters() -> None:
    paths = [
        PACKAGE / "projects" / "service.py",
        PACKAGE / "artifacts" / "cleanup.py",
        PACKAGE / "transaction.py",
        PACKAGE / "accounts" / "identity.py",
        PACKAGE / "accounts" / "builtin.py",
        PACKAGE / "access" / "authorization.py",
    ]
    paths.extend(PACKAGE.glob("*/store.py"))
    for path in paths:
        for module in imported_modules(path):
            assert not module.startswith(("sqlalchemy", "polycolab.db", "fastapi")), (
                f"{path.name} imports {module}"
            )


def test_capability_implementation_does_not_import_http_routes() -> None:
    for capability in (
        "access",
        "accounts",
        "agents",
        "artifacts",
        "catalogue",
        "execution",
        "model_gateway",
        "operations",
        "platform",
        "research",
        "verification",
        "projects",
    ):
        for path in (PACKAGE / capability).rglob("*.py"):
            if "routes" in path.parts:
                continue
            for module in imported_modules(path):
                assert ".routes" not in module, f"{path.relative_to(PACKAGE)} imports {module}"


def test_removed_internal_facades_do_not_return() -> None:
    for relative in (
        "api",
        "models.py",
        "schemas.py",
        "platform/database.py",
        "accounts/local.py",
        "accounts/persistence.py",
        "projects/persistence.py",
        "research/persistence.py",
        "unit_of_work.py",
        "db/unit_of_work.py",
        "db/repositories",
        "db/mappings",
        "db/models/base.py",
        "db/sqlite_migrations",
    ):
        path = PACKAGE / relative
        if path.is_dir():
            assert not list(path.rglob("*.py"))
        else:
            assert not path.exists()


def test_removed_persistence_modules_are_not_imported() -> None:
    removed = (
        "polycolab.accounts.local",
        "polycolab.accounts.persistence",
        "polycolab.projects.persistence",
        "polycolab.research.persistence",
        "polycolab.unit_of_work",
        "polycolab.db.unit_of_work",
        "polycolab.db.repositories",
        "polycolab.db.mappings",
        "polycolab.db.models.base",
    )
    paths = list(PACKAGE.rglob("*.py")) + list((PACKAGE.parents[2] / "tests").rglob("*.py"))
    for path in paths:
        for module in imported_modules(path):
            assert not any(module == old or module.startswith(old + ".") for old in removed), (
                f"{path} imports removed module {module}"
            )
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module == "polycolab.db.models":
                assert not {alias.name for alias in node.names} & {"Base", "utc_now"}, (
                    f"{path} imports primitives through the model registry"
                )
