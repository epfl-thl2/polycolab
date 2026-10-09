"""Verify and stage a recovery set without touching live databases or volumes."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO

COMPONENTS = (
    "postgres.dump.age",
    "garage-metadata.tar.age",
    "garage-data.tar.age",
    "key-material.tar.age",
)
MARKER = b"polycolab-recovery-v1\n"


def regular_file(path: Path) -> BinaryIO:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise ValueError("invalid_file")
    return os.fdopen(fd, "rb")


def decrypt(source: BinaryIO, target: BinaryIO, identity: Path, limit: int) -> None:
    with subprocess.Popen(
        ["age", "--decrypt", "--identity", str(identity)],
        stdin=source,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as process:
        try:
            assert process.stdout is not None
            count = 0
            while chunk := process.stdout.read(min(1024 * 1024, limit - count + 1)):
                count += len(chunk)
                if count > limit:
                    raise ValueError("size_limit")
                target.write(chunk)
            if process.wait(timeout=10) != 0:
                raise ValueError("decryption_failed")
        except BaseException:
            process.kill()
            process.wait()
            raise


def extract_regular_archive(archive: Path, target: Path, limit: int, max_files: int) -> None:
    """Reject links/devices/traversal and duplicates; never restore archive ownership."""
    target.mkdir(mode=0o700)
    seen: set[str] = set()
    total = 0
    with tarfile.open(archive, mode="r|") as stream:
        for index, member in enumerate(stream):
            if index >= max_files:
                raise ValueError("member_limit")
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isdir() or member.isfile()):
                raise ValueError("unsafe_archive")
            if str(path) == "." and member.isdir():
                continue
            if str(path) in seen:
                raise ValueError("duplicate_archive_path")
            seen.add(str(path))
            destination = target.joinpath(*path.parts)
            if member.isdir():
                destination.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            total += member.size
            if member.size < 0 or total > limit:
                raise ValueError("expanded_size_limit")
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            source = stream.extractfile(member)
            if source is None:
                raise ValueError("missing_archive_body")
            with source, destination.open("xb") as output:
                os.chmod(destination, 0o600)
                shutil.copyfileobj(source, output, length=1024 * 1024)


def stage_restore(
    bundle: Path, parent: Path, identity: Path, *, max_bytes: int, max_files: int
) -> Path:
    for directory in (bundle, parent):
        if (
            not directory.is_absolute()
            or directory.resolve() != directory
            or not directory.is_dir()
        ):
            raise ValueError("canonical_directory_required")
    if parent == bundle or bundle in parent.parents or parent in bundle.parents:
        raise ValueError("overlapping_directories")
    if set(os.listdir(bundle)) != {*COMPONENTS, "manifest.age", "COMPLETE"}:
        raise ValueError("invalid_members")
    with regular_file(bundle / "COMPLETE") as marker:
        if marker.read(128) != MARKER:
            raise ValueError("incomplete_backup")
    # This private root is retained on failure for explicit operator inspection.
    # It never overwrites an existing target or creates a live service.
    destination = Path(tempfile.mkdtemp(prefix="recovery-set-", dir=parent))
    with regular_file(bundle / "manifest.age") as source, tempfile.TemporaryFile() as manifest:
        decrypt(source, manifest, identity, 4096)
        manifest.seek(0)
        lines = manifest.read().decode("ascii").splitlines()
    if (
        len(lines) != 7
        or lines[0] != "format=polycolab-recovery-v1"
        or re.fullmatch(r"release=[a-f0-9]{7,64}", lines[1]) is None
        or re.fullmatch(r"schema=[a-zA-Z0-9_]{1,128}", lines[2]) is None
    ):
        raise ValueError("invalid_manifest")
    # Copy pinned ciphertext while hashing, then decrypt the verified private copy.
    # A concurrently replaced source cannot change what is subsequently decrypted.
    for name, line in zip(COMPONENTS, lines[3:], strict=True):
        match = re.fullmatch(r"([a-f0-9]{64})  " + re.escape(name), line)
        if match is None:
            raise ValueError("invalid_checksum_entry")
        digest = hashlib.sha256()
        count = 0
        with regular_file(bundle / name) as source, tempfile.TemporaryFile() as ciphertext:
            while chunk := source.read(1024 * 1024):
                count += len(chunk)
                if count > max_bytes:
                    raise ValueError("ciphertext_size_limit")
                digest.update(chunk)
                ciphertext.write(chunk)
            if digest.hexdigest() != match[1]:
                raise ValueError("checksum_mismatch")
            ciphertext.seek(0)
            output_path = destination / name.removesuffix(".age")
            with output_path.open("xb") as output:
                os.chmod(output_path, 0o600)
                decrypt(ciphertext, output, identity, max_bytes)
        if name.endswith(".tar.age"):
            extract_regular_archive(
                output_path, destination / name.removesuffix(".tar.age"), max_bytes, max_files
            )
    (destination / "STAGED").write_bytes(MARKER)
    os.chmod(destination / "STAGED", 0o600)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("destination_parent", type=Path)
    parser.add_argument("--identity", required=True, type=Path)
    parser.add_argument("--isolated-target", action="store_true", required=True)
    parser.add_argument("--max-bytes", type=int, default=100 * 1024**3)
    parser.add_argument("--max-files", type=int, default=1_000_000)
    args = parser.parse_args()
    if not 1 <= args.max_bytes <= 1024**5 or not 1 <= args.max_files <= 10_000_000:
        parser.error("invalid resource bound")
    try:
        staged = stage_restore(
            args.bundle,
            args.destination_parent,
            args.identity,
            max_bytes=args.max_bytes,
            max_files=args.max_files,
        )
    except Exception:
        print(
            "recovery set: FAILED; any partial private staging is retained; no live state changed"
        )
        return 1
    print("recovery set: STAGED; not activated; agent ingress must remain disabled")
    print(staged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
