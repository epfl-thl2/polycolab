"""Restore staging safety checks; not a live database/key recovery drill."""

import io
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from polycolab.operations.recovery_set import extract_regular_archive, stage_restore


def archive_with(tmp_path: Path, members: list[tarfile.TarInfo]) -> Path:
    archive = tmp_path / "input.tar"
    with tarfile.open(archive, "w") as output:
        for member in members:
            output.addfile(member, io.BytesIO(b"x" * member.size))
    return archive


def test_restore_regular_files_are_private(tmp_path: Path) -> None:
    member = tarfile.TarInfo("./nested/data")
    member.size = 3
    member.mode = 0o777
    archive = archive_with(tmp_path, [member])
    target = tmp_path / "target"
    extract_regular_archive(archive, target, 10, 10)
    assert (target / "nested/data").read_bytes() == b"xxx"
    assert (target / "nested/data").stat().st_mode & 0o777 == 0o600
    assert target.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("name", ["../escape", "/absolute", "nested/../../escape"])
def test_restore_rejects_path_escape(tmp_path: Path, name: str) -> None:
    archive = archive_with(tmp_path, [tarfile.TarInfo(name)])
    with pytest.raises(ValueError, match="unsafe_archive"):
        extract_regular_archive(archive, tmp_path / "target", 10, 10)
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize(
    "kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE]
)
def test_restore_rejects_links_and_special_files(tmp_path: Path, kind: bytes) -> None:
    member = tarfile.TarInfo("entry")
    member.type = kind
    member.linkname = "../../outside"
    archive = archive_with(tmp_path, [member])
    with pytest.raises(ValueError, match="unsafe_archive"):
        extract_regular_archive(archive, tmp_path / "target", 10, 10)


def test_restore_rejects_duplicate_path(tmp_path: Path) -> None:
    archive = archive_with(tmp_path, [tarfile.TarInfo("entry"), tarfile.TarInfo("./entry")])
    with pytest.raises(ValueError, match="duplicate_archive_path"):
        extract_regular_archive(archive, tmp_path / "target", 10, 10)


def test_restore_bounds_expanded_bytes(tmp_path: Path) -> None:
    member = tarfile.TarInfo("entry")
    member.size = 11
    archive = archive_with(tmp_path, [member])
    with pytest.raises(ValueError, match="expanded_size_limit"):
        extract_regular_archive(archive, tmp_path / "target", 10, 10)


def test_restore_bounds_members_and_preserves_existing_target(tmp_path: Path) -> None:
    archive = archive_with(tmp_path, [tarfile.TarInfo("a"), tarfile.TarInfo("b")])
    target = tmp_path / "target"
    with pytest.raises(ValueError, match="member_limit"):
        extract_regular_archive(archive, target, 10, 1)
    with pytest.raises(FileExistsError):
        extract_regular_archive(archive, target, 10, 10)
    assert (target / "a").exists()


@pytest.fixture
def captured_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Actual capture script/tar; fake age/pg_dump. Not encryption/PG evidence."""
    tools = tmp_path / "tools"
    tools.mkdir()
    for name, script in {
        "age": "#!/bin/sh\ncat\n",
        "pg_dump": "#!/bin/sh\nprintf 'synthetic-database-dump'\n",
    }.items():
        executable = tools / name
        executable.write_text(script)
        executable.chmod(0o700)
    monkeypatch.setenv("PATH", f"{tools}:{os.environ['PATH']}")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PGSERVICE", "synthetic")
    monkeypatch.setenv("BACKUP_ENCRYPTION_RECIPIENT", "synthetic")
    monkeypatch.setenv("RELEASE_SHA", "abcdef123")
    monkeypatch.setenv("RECOVERY_SCHEMA_HEAD", "synthetic_head")
    monkeypatch.setenv("RECOVERY_WRITERS_QUIESCED", "yes")
    monkeypatch.setenv("RECOVERY_GARAGE_STOPPED", "yes")
    for variable, directory in (
        ("RECOVERY_GARAGE_METADATA_DIR", "metadata"),
        ("RECOVERY_GARAGE_DATA_DIR", "data"),
        ("RECOVERY_KEY_MATERIAL_DIR", "keys"),
    ):
        source = tmp_path / directory
        source.mkdir()
        (source / "content").write_text(f"synthetic-{directory}")
        monkeypatch.setenv(variable, str(source.resolve()))
    backups = tmp_path / "backups"
    backups.mkdir()
    capture_script = Path(__file__).resolve().parents[2] / "deploy/scripts/backup-recovery-set.sh"
    result = subprocess.run(
        ["bash", str(capture_script), str(backups.resolve())],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return next(backups.iterdir()).resolve()


def test_capture_stages_all_components(captured_bundle: Path, tmp_path: Path) -> None:
    parent = tmp_path / "staging"
    parent.mkdir()
    staged = stage_restore(
        captured_bundle,
        parent.resolve(),
        tmp_path / "synthetic-identity",
        max_bytes=1_000_000,
        max_files=100,
    )
    assert (staged / "postgres.dump").read_bytes() == b"synthetic-database-dump"
    assert (staged / "garage-metadata/content").read_text() == "synthetic-metadata"
    assert (staged / "garage-data/content").read_text() == "synthetic-data"
    assert (staged / "key-material/content").read_text() == "synthetic-keys"
    assert (staged / "STAGED").exists()


def test_corruption_never_marks_staging_complete(captured_bundle: Path, tmp_path: Path) -> None:
    (captured_bundle / "garage-data.tar.age").write_bytes(b"corrupt")
    parent = tmp_path / "staging"
    parent.mkdir()
    with pytest.raises(ValueError, match="checksum_mismatch"):
        stage_restore(
            captured_bundle,
            parent.resolve(),
            tmp_path / "synthetic-identity",
            max_bytes=1_000_000,
            max_files=100,
        )
    assert not list(parent.glob("*/STAGED"))
