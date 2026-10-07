"""Content-free restore manifest checks; not a live restore drill."""

from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from polycolab.db.models import SqlGatewayProfile, SqlUser
from polycolab.operations import recovery_integrity
from polycolab.operations.recovery_integrity import capture_manifest, main, manifest_mismatches

KEY = b"recovery-integrity-test-key-32b!"


def test_manifest_is_deterministic_keyed_and_contains_no_values(client: TestClient) -> None:
    app = cast(Any, client.app)
    with app.state.session_factory() as session:
        user = SqlUser(
            issuer="https://private-issuer.example",
            subject="private-subject",
            email="private@example.test",
        )
        session.add(user)
        session.flush()
        session.add(
            SqlGatewayProfile(
                user_id=user.id,
                display_name="private-profile",
                base_url="https://models.example/v1",
                model_id="private-model",
                encrypted_credential=b"private-ciphertext",
                wrapped_data_key=b"private-wrapped-key",
                encryption_key_version="private-key-version",
            )
        )
        session.commit()
        first = capture_manifest(
            session,
            key=KEY,
            schema_revision="test-revision",
            table_names=("users", "gateway_profiles"),
        )
        second = capture_manifest(
            session,
            key=KEY,
            schema_revision="test-revision",
            table_names=("gateway_profiles", "users"),
        )
        assert first == second
        rendered = str(first)
        for private in (
            "private-subject",
            "private@example.test",
            "private-profile",
            "private-ciphertext",
            "private-key-version",
        ):
            assert private not in rendered


def test_manifest_detects_exact_row_schema_and_key_changes(client: TestClient) -> None:
    app = cast(Any, client.app)
    with app.state.session_factory() as session:
        user = SqlUser(issuer="issuer", subject="subject", display_name="Before")
        session.add(user)
        session.commit()
        expected = capture_manifest(
            session, key=KEY, schema_revision="revision-a", table_names=("users",)
        )
        user.display_name = "After"
        session.commit()
        changed = capture_manifest(
            session, key=KEY, schema_revision="revision-a", table_names=("users",)
        )
        assert manifest_mismatches(expected, changed) == ("users",)
        other_key = capture_manifest(
            session,
            key=b"different-recovery-integrity-key",
            schema_revision="revision-a",
            table_names=("users",),
        )
        assert manifest_mismatches(changed, other_key) == ("users",)
        other_revision = {**changed, "schema_revision": "revision-b"}
        assert manifest_mismatches(changed, other_revision) == ("$schema_revision",)


@pytest.mark.parametrize(
    "key,revision,tables",
    [
        (b"short", "revision", ("users",)),
        (KEY, "", ("users",)),
        (KEY, "revision", ("users", "users")),
        (KEY, "revision", ("unknown",)),
    ],
)
def test_manifest_rejects_unsafe_inputs(
    client: TestClient, key: bytes, revision: str, tables: tuple[str, ...]
) -> None:
    app = cast(Any, client.app)
    with app.state.session_factory() as session, pytest.raises(ValueError):
        capture_manifest(session, key=key, schema_revision=revision, table_names=tables)


def test_manifest_file_is_private_and_never_overwritten(tmp_path: Path) -> None:
    output = tmp_path / "manifest.json"
    manifest = {"format": "synthetic"}
    recovery_integrity._write_new(output, manifest)
    assert output.stat().st_mode & 0o777 == 0o600
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        recovery_integrity._write_new(output, {"format": "replacement"})
    assert output.read_bytes() == original


def test_cli_failure_is_normalized_without_exception_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("RECOVERY_MANIFEST_HMAC_KEY", "a" * 32)

    def fail(_: bytes) -> dict[str, object]:
        raise RuntimeError("private-database-diagnostic")

    monkeypatch.setattr(recovery_integrity, "_capture_database", fail)
    assert main(["capture", "--output", str(tmp_path / "manifest.json")]) == 1
    captured = capsys.readouterr()
    assert "RECOVERY_INTEGRITY_FAILURE" in captured.out
    assert "private-database-diagnostic" not in captured.out + captured.err
