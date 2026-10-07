"""Read-only PostgreSQL bundle verification; integrity, not authenticity."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path


class InvalidBackupBundle(ValueError):
    pass


def _open(directory: int, name: str) -> int:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise InvalidBackupBundle("invalid_file")
    return fd


def _small(directory: int, name: str, limit: int) -> bytes:
    fd = _open(directory, name)
    try:
        data = os.read(fd, limit + 1)
        if len(data) > limit:
            raise InvalidBackupBundle("oversized_metadata")
        return data
    finally:
        os.close(fd)


def verify_bundle(path: Path) -> bool:
    """Stream ciphertext/plaintext checksum; return whether bundle is encrypted.

    Files are opened relative to a pinned, non-symlink directory. No filename
    from checksum content is ever opened or passed to a command. This does not
    decrypt archives, validate PostgreSQL contents, or authenticate their source.
    """
    directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        names = set(os.listdir(directory))
        encrypted = "postgres.dump.age" in names
        dump = "postgres.dump.age" if encrypted else "postgres.dump"
        if names != {dump, dump + ".sha256", "COMPLETE"}:
            raise InvalidBackupBundle("unexpected_bundle_members")
        marker = _small(directory, "COMPLETE", 64)
        if marker != b"polycolab-postgres-backup-v1\n":
            raise InvalidBackupBundle("invalid_completion_marker")
        checksum = _small(directory, dump + ".sha256", 128)
        fd = _open(directory, dump)
        try:
            before = os.fstat(fd)
            digest = hashlib.sha256()
            size = 0
            while chunk := os.read(fd, 1024 * 1024):
                size += len(chunk)
                if size > before.st_size:
                    raise InvalidBackupBundle("backup_changed")
                digest.update(chunk)
            after = os.fstat(fd)
            if (
                size == 0
                or size != before.st_size
                or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            ):
                raise InvalidBackupBundle("empty_or_changed_backup")
            expected = f"{digest.hexdigest()}  {dump}\n".encode("ascii")
            if checksum != expected:
                raise InvalidBackupBundle("checksum_mismatch")
        finally:
            os.close(fd)
        return encrypted
    finally:
        os.close(directory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)
    try:
        encrypted = verify_bundle(args.bundle)
    except OSError, ValueError:
        print(json.dumps({"status": "INVALID_BACKUP_BUNDLE"}))
        return 1
    print(json.dumps({"status": "CHECKSUM_VERIFIED", "encrypted": encrypted}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
