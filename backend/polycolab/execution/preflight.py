"""Read-only Linux host checks, plus explicit loading of a curated OCI archive.

Run as the dedicated execution account. Loading is an operator preparation step,
never part of an admitted attempt and never uses provider or service credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tomllib
from pathlib import Path

from polycolab.execution.linux import LinuxRuntime
from polycolab.execution.service import ServiceConfig, exclusive_controller_state


async def image_check(reference: str, archive: str | None) -> None:
    from microsandbox import Image

    if archive is not None:
        await Image.load(archive)
    image = await Image.get(reference)
    expected = reference.rsplit("@sha256:", 1)[-1]
    if (
        image.manifest_digest not in {expected, "sha256:" + expected}
        or image.architecture not in {"amd64", "x86_64"}
        or image.os != "linux"
    ):
        raise ValueError("cached image identity mismatch")


async def check(config: ServiceConfig, archive: Path | None) -> None:
    runtime = LinuxRuntime(Path(config.state_dir), config.images, config.capacity)
    await runtime.check_ready()
    with exclusive_controller_state(Path(config.state_dir)):
        for ordinal in range(config.capacity):
            slot = Path(config.state_dir) / "slots" / str(ordinal)
            for image in config.images:
                args = [
                    sys.executable,
                    "-m",
                    "polycolab.execution.preflight",
                    "--image",
                    image.reference,
                ]
                if archive is not None:
                    args.extend(["--archive", str(archive.resolve())])
                child = await asyncio.create_subprocess_exec(
                    *args,
                    env={**os.environ, "MSB_HOME": str(slot / "msb")},
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    async with asyncio.timeout(300):
                        if await child.wait() != 0:
                            raise ValueError("slot image check failed")
                finally:
                    if child.returncode is None:
                        child.kill()
                        await child.wait()
    print(
        "Host prerequisites and cached image identities passed; native acceptance still required."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--image", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.image:
            asyncio.run(image_check(args.image, str(args.archive) if args.archive else None))
        else:
            if args.config is None:
                parser.error("--config required")
            with args.config.open("rb") as stream:
                config = ServiceConfig.model_validate(tomllib.load(stream))
            asyncio.run(check(config, args.archive))
    except Exception:
        print(
            "Execution preflight failed; check host prerequisites and pinned image cache.",
            file=sys.stderr,
        )
        return 78
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
