"""One credential-free microsandbox executor, launched only in a bounded unit."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from polycolab.execution.linux import isolated_executor
from polycolab.execution.microsandbox import ImagePolicy, MicrosandboxRuntime, SdkProcess
from polycolab.verification.contracts import ResourceLimits


async def execute(config_path: Path) -> None:
    isolated_executor()
    from microsandbox import Rlimit, Sandbox, Stdin

    config = json.loads(config_path.read_text())
    work = Path(config["work"])
    limits = ResourceLimits.model_validate(config["limits"])
    deadline = datetime.fromisoformat(config["deadline"])
    runtime = MicrosandboxRuntime(work / "runtime")
    # MSB_HOME is unique to this physical slot. Previous units have been stopped
    # before reuse; never touch a sandbox in another controller/slot namespace.
    page = await Sandbox.list_with(labels={"owner": "polycolab-execution"})
    if page.next_cursor is not None:
        raise RuntimeError("orphan_limit_exceeded")
    for orphan in page.sandboxes:
        await orphan.kill(timeout=5)
        await orphan.wait_until_stopped()
        await orphan.remove()
    inputs = {
        path.relative_to(work / "inputs").as_posix(): path.read_bytes()
        for path in (work / "inputs").rglob("*")
        if path.is_file()
    }
    image = ImagePolicy(config["image"], "AGENT", "0.154.0", "0" * 64, "0" * 64, "linux-x86_64")
    async with runtime.attempt(
        name=config["name"],
        image=image,
        limits=limits,
        deadline=deadline,
        inputs=inputs,
        output_dir=work / "outputs",
    ) as (sandbox, _):
        handle = await sandbox.exec_stream(
            "python3",
            ["/opt/polycolab/guest_bridge.py"],
            stdin=Stdin.pipe(),
            tty=False,
            rlimits=[Rlimit.cpu(limits.cpu_seconds), Rlimit.nproc(limits.process_count)],
        )
        channel = SdkProcess(handle, limits.log_bytes)
        reader = asyncio.StreamReader(limit=2_000_000)
        await asyncio.get_running_loop().connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer
        )
        sys.stdout.buffer.write(b'{"kind":"ready"}\n')
        sys.stdout.buffer.flush()

        async def inbound() -> None:
            while data := await reader.readline():
                await channel.send(data)

        async def outbound() -> None:
            while (data := await channel.receive()) is not None:
                sys.stdout.buffer.write(data + b"\n")
                sys.stdout.buffer.flush()

        incoming, outgoing = asyncio.create_task(inbound()), asyncio.create_task(outbound())
        try:
            done, _ = await asyncio.wait((incoming, outgoing), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                await task
        finally:
            incoming.cancel()
            outgoing.cancel()
            await asyncio.gather(incoming, outgoing, return_exceptions=True)


def main() -> int:
    try:
        asyncio.run(execute(Path(sys.argv[1])))
    except Exception:
        # Neither provider details nor researcher code belongs in host journals.
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
