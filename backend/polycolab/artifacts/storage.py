"""Bounded Garage byte storage; callers own authorization and durable lifecycle.

Never derive access from a digest or expose keys to clients. Each staging attempt
gets a fresh key: Garage versioning is not required. Only the domain GC, after
claiming an expired staging row, may call delete. No database I/O belongs here.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, Protocol

if TYPE_CHECKING:
    from polycolab.platform.config import Settings
from urllib.parse import urlsplit
from uuid import uuid4

from polycolab.entities.artifacts import MAX_ARTIFACT_BYTES as MAX_ARTIFACT_BYTES
from polycolab.entities.artifacts import ArtifactIntegrity as ArtifactIntegrity
from polycolab.entities.artifacts import ArtifactStorageError as ArtifactStorageError

READ_CHUNK_BYTES = 64 * 1024


def new_staging_key() -> str:
    """Persist this opaque key before attempting storage I/O, including retries."""
    return f"artifacts/{uuid4().hex}"


def _validate_key(key: str) -> None:
    if re.fullmatch(r"artifacts/[0-9a-f]{32}", key) is None:
        raise ArtifactStorageError("artifact_invalid_storage_key")


def verified_bytes(source: BinaryIO, expected: ArtifactIntegrity) -> bytes:
    """Read at most the declared size plus one byte; verify before exposing bytes.

    The caller owns the source and its transport deadline. Never use unbounded
    read(), and never stream unchecked storage bytes to a browser or runner.
    """
    content = bytearray()
    digest = hashlib.sha256()
    while True:
        chunk = source.read(min(READ_CHUNK_BYTES, expected.byte_length - len(content) + 1))
        if not chunk:
            break
        if len(content) + len(chunk) > expected.byte_length:
            raise ArtifactStorageError("artifact_length_mismatch")
        content.extend(chunk)
        digest.update(chunk)
    if len(content) != expected.byte_length:
        raise ArtifactStorageError("artifact_length_mismatch")
    if digest.hexdigest() != expected.sha256:
        raise ArtifactStorageError("artifact_digest_mismatch")
    return bytes(content)


class ArtifactStorage(Protocol):
    def put_verified(self, key: str, source: BinaryIO, expected: ArtifactIntegrity) -> None: ...
    def get_verified(self, key: str, expected: ArtifactIntegrity) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class FilesystemStorage:
    """Local-only opaque blobs; reads still pass through application authorization."""

    root: Path

    def __post_init__(self) -> None:
        # Configuration is trusted; canonicalize OS aliases such as macOS /var.
        # Request keys and descendants must still never follow symlinks.
        object.__setattr__(self, "root", self.root.resolve())

    def _directory(self) -> int:
        directory = self.root.absolute() / "artifacts"
        if any(part.is_symlink() for part in (directory, *directory.parents)):
            raise ArtifactStorageError("artifact_invalid_storage_key")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        return os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def put_verified(self, key: str, source: BinaryIO, expected: ArtifactIntegrity) -> None:
        _validate_key(key)
        content = verified_bytes(source, expected)
        temporary = f".{key.split('/')[1]}.tmp"
        try:
            directory = self._directory()
            try:
                fd = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory,
                )
                try:
                    with os.fdopen(fd, "wb") as target:
                        target.write(content)
                        target.flush()
                        os.fsync(target.fileno())
                    os.link(
                        temporary,
                        key.split("/")[1],
                        src_dir_fd=directory,
                        dst_dir_fd=directory,
                        follow_symlinks=False,
                    )
                finally:
                    os.unlink(temporary, dir_fd=directory)
            finally:
                os.close(directory)
        except OSError:
            raise ArtifactStorageError("artifact_storage_unavailable") from None
        self.get_verified(key, expected)

    def get_verified(self, key: str, expected: ArtifactIntegrity) -> bytes:
        _validate_key(key)
        try:
            directory = self._directory()
            try:
                fd = os.open(key.split("/")[1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                with os.fdopen(fd, "rb") as source:
                    return verified_bytes(source, expected)
            finally:
                os.close(directory)
        except OSError:
            raise ArtifactStorageError("artifact_storage_unavailable") from None

    def delete(self, key: str) -> None:
        _validate_key(key)
        try:
            directory = self._directory()
            try:
                for name in (key.split("/")[1], f".{key.split('/')[1]}.tmp"):
                    try:
                        os.unlink(name, dir_fd=directory)
                    except FileNotFoundError:
                        pass
            finally:
                os.close(directory)
        except OSError:
            raise ArtifactStorageError("artifact_storage_unavailable") from None

    def close(self) -> None:
        pass


@dataclass(frozen=True)
class GarageStorage:
    """Service-owned bucket client, never constructed from request parameters.

    put_verified must only receive a freshly reserved staging key. Application
    state fences competing upload/commit/GC calls; S3 is not the state authority.
    """

    client: Any = field(repr=False)
    bucket: str

    def close(self) -> None:
        self.client.close()

    def put_verified(self, key: str, source: BinaryIO, expected: ArtifactIntegrity) -> None:
        _validate_key(key)
        content = verified_bytes(source, expected)
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                ContentLength=expected.byte_length,
                ContentType="application/octet-stream",
                ContentMD5=base64.b64encode(
                    hashlib.md5(content, usedforsecurity=False).digest()
                ).decode("ascii"),
            )
        except Exception:
            # Ambiguous writes leave the staging row for GC; never claim commit.
            raise ArtifactStorageError("artifact_storage_unavailable") from None
        # Do not trust an ETag or a successful PUT as proof of canonical bytes.
        self.get_verified(key, expected)

    def get_verified(self, key: str, expected: ArtifactIntegrity) -> bytes:
        _validate_key(key)
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"]
            try:
                if response["ContentLength"] != expected.byte_length:
                    raise ArtifactStorageError("artifact_length_mismatch")
                return verified_bytes(body, expected)
            finally:
                body.close()
        except ArtifactStorageError:
            raise
        except Exception:
            raise ArtifactStorageError("artifact_storage_unavailable") from None

    def delete(self, key: str) -> None:
        """Delete a domain-claimed staging tombstone; no prefix/list-based sweep."""
        _validate_key(key)
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception:
            raise ArtifactStorageError("artifact_storage_unavailable") from None


def garage_storage(
    *, endpoint: str, bucket: str, region: str, access_key: str, secret_key: str
) -> GarageStorage:
    """Explicit credentials prevent ambient instance-role credential discovery."""
    import boto3  # type: ignore[import-untyped]
    from botocore.config import Config  # type: ignore[import-untyped]

    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or not all((bucket, region, access_key, secret_key))
    ):
        raise ArtifactStorageError("artifact_storage_configuration_invalid")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=3,
            read_timeout=10,
            retries={"mode": "standard", "total_max_attempts": 2},
            max_pool_connections=8,
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )
    return GarageStorage(client=client, bucket=bucket)


def configured_storage(settings: Settings) -> ArtifactStorage:
    if settings.artifact_local_directory is not None:
        return FilesystemStorage(settings.artifact_local_directory)
    if not settings.artifact_storage_configured:
        raise ArtifactStorageError("artifact_storage_unavailable")
    assert settings.artifact_s3_endpoint is not None
    assert settings.artifact_s3_bucket is not None
    assert settings.artifact_s3_region is not None
    assert settings.artifact_s3_access_key is not None
    assert settings.artifact_s3_secret_key is not None
    return garage_storage(
        endpoint=str(settings.artifact_s3_endpoint),
        bucket=settings.artifact_s3_bucket,
        region=settings.artifact_s3_region,
        access_key=settings.artifact_s3_access_key.get_secret_value(),
        secret_key=settings.artifact_s3_secret_key.get_secret_value(),
    )
