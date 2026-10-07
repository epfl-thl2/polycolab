import hashlib
from pathlib import Path

import pytest

from polycolab.operations.backup import InvalidBackupBundle, main, verify_bundle


def bundle(root: Path, encrypted: bool = True) -> Path:
    root.mkdir()
    name = "postgres.dump.age" if encrypted else "postgres.dump"
    data = b"synthetic backup bytes"
    (root / name).write_bytes(data)
    (root / (name + ".sha256")).write_text(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    (root / "COMPLETE").write_text("polycolab-postgres-backup-v1\n")
    return root


@pytest.mark.parametrize("encrypted", [True, False])
def test_verifies_relocated_bundle_without_mutation(tmp_path: Path, encrypted: bool) -> None:
    root = bundle(tmp_path / "original", encrypted)
    root = root.rename(tmp_path / "copied")
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    assert verify_bundle(root) is encrypted
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before


@pytest.mark.parametrize("member", ["COMPLETE", "postgres.dump.age", "postgres.dump.age.sha256"])
def test_rejects_missing_corrupt_or_symlinked_members(tmp_path: Path, member: str) -> None:
    root = bundle(tmp_path / "bundle")
    original = (root / member).read_bytes()
    (root / member).unlink()
    with pytest.raises(InvalidBackupBundle):
        verify_bundle(root)
    (root / member).write_bytes(b"corrupt")
    with pytest.raises(InvalidBackupBundle):
        verify_bundle(root)
    (root / member).unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(original)
    (root / member).symlink_to(outside)
    with pytest.raises(OSError):
        verify_bundle(root)


def test_rejects_extra_files_and_ambiguous_archive(tmp_path: Path) -> None:
    root = bundle(tmp_path / "bundle")
    (root / "postgres.dump").write_bytes(b"extra")
    with pytest.raises(InvalidBackupBundle):
        verify_bundle(root)


def test_rejects_checksum_path_injection(tmp_path: Path) -> None:
    root = bundle(tmp_path / "bundle")
    (root / "postgres.dump.age.sha256").write_text("0" * 64 + "  ../../private\n")
    with pytest.raises(InvalidBackupBundle, match="checksum_mismatch"):
        verify_bundle(root)


def test_rejects_hard_link(tmp_path: Path) -> None:
    root = bundle(tmp_path / "bundle")
    (tmp_path / "alias").hardlink_to(root / "postgres.dump.age")
    with pytest.raises(InvalidBackupBundle, match="invalid_file"):
        verify_bundle(root)


def test_rejects_empty_archive_even_with_correct_checksum(tmp_path: Path) -> None:
    root = bundle(tmp_path / "bundle")
    (root / "postgres.dump.age").write_bytes(b"")
    (root / "postgres.dump.age.sha256").write_text(
        f"{hashlib.sha256(b'').hexdigest()}  postgres.dump.age\n"
    )
    with pytest.raises(InvalidBackupBundle, match="empty_or_changed"):
        verify_bundle(root)


def test_rejects_symlinked_directory(tmp_path: Path) -> None:
    root = bundle(tmp_path / "bundle")
    link = tmp_path / "link"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(OSError):
        verify_bundle(link)


def test_cli_does_not_echo_private_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path / "private-name")]) == 1
    assert capsys.readouterr().out == '{"status": "INVALID_BACKUP_BUNDLE"}\n'
