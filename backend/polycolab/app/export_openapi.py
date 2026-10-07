"""Export the deterministic OpenAPI snapshot for the TypeScript client."""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path

from polycolab.app.application import create_app

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPOSITORY_ROOT / "packages" / "api-client" / "openapi.json"


def serialized_openapi() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = ArgumentParser(description="Export the deterministic FastAPI OpenAPI snapshot.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    output = arguments.output
    document = serialized_openapi()
    if arguments.check:
        if not output.is_file() or output.read_text(encoding="utf-8") != document:
            print(f"OpenAPI snapshot is stale: {output}", file=sys.stderr)
            raise SystemExit(1)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")


if __name__ == "__main__":
    main()
