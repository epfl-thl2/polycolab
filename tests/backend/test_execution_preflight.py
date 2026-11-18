"""Archive imports must register and verify the immutable controller reference."""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from polycolab.execution.preflight import image_check


@pytest.mark.parametrize("matches", [True, False])
def test_archive_import_registers_digest_and_checks_actual_identity(
    monkeypatch: pytest.MonkeyPatch, matches: bool
) -> None:
    reference = "example/agent@sha256:" + "a" * 64
    image = SimpleNamespace(
        manifest_digest="sha256:" + ("a" if matches else "b") * 64,
        architecture="amd64",
        os="linux",
    )
    sdk = SimpleNamespace(load=AsyncMock(), get=AsyncMock(return_value=image))
    monkeypatch.setitem(sys.modules, "microsandbox", SimpleNamespace(Image=sdk))
    if matches:
        asyncio.run(image_check(reference, "/tmp/agent.tar"))
    else:
        with pytest.raises(ValueError, match="cached image identity mismatch"):
            asyncio.run(image_check(reference, "/tmp/agent.tar"))
    sdk.load.assert_awaited_once_with("/tmp/agent.tar", tag=reference)
    sdk.get.assert_awaited_once_with(reference)
