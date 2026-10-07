from __future__ import annotations

import ast
from pathlib import Path


def test_production_worker_modules_do_not_import_persistence_or_legacy_harness() -> None:
    package_dir = Path(__file__).resolve().parents[2] / "backend" / "polycolab"
    modules = (
        "agents/worker.py",
        "agents/runtime/remote.py",
        "agents/runtime/gateways.py",
    )
    forbidden = (
        "sqlalchemy",
        "polycolab.agents.runtime.builtin",
        "polycolab.agents.context",
        "polycolab.db",
        "polycolab.model_gateway.service",
        "polycolab.agents.sessions",
        "polycolab.agents.tools",
    )
    violations: list[str] = []
    for module in modules:
        tree = ast.parse((package_dir / module).read_text(), filename=module)
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                names = [node.module]
            for name in names:
                if any(name == item or name.startswith(item + ".") for item in forbidden):
                    violations.append(f"{module}:{getattr(node, 'lineno', 0)}: {name}")
    assert violations == []
