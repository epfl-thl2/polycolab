from __future__ import annotations

import hashlib
from io import BytesIO
from typing import Any
from unittest.mock import Mock

import pytest

from polycolab.artifacts.storage import (
    MAX_ARTIFACT_BYTES,
    READ_CHUNK_BYTES,
    ArtifactIntegrity,
    ArtifactStorageError,
    GarageStorage,
    garage_storage,
    new_staging_key,
    verified_bytes,
)


def integrity(data: bytes) -> ArtifactIntegrity:
    return ArtifactIntegrity(hashlib.sha256(data).hexdigest(), len(data))


@pytest.mark.parametrize("data", [b"", b"hello", b"x" * (READ_CHUNK_BYTES + 3)])
def test_verification_uses_bounded_reads(data: bytes) -> None:
    class BoundedSource(BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            assert size is not None and 0 < size <= READ_CHUNK_BYTES
            return super().read(size)

    assert verified_bytes(BoundedSource(data), integrity(data)) == data


@pytest.mark.parametrize(
    ("data", "expected", "code"),
    [
        (b"abcd", integrity(b"abc"), "artifact_length_mismatch"),
        (b"ab", integrity(b"abc"), "artifact_length_mismatch"),
        (b"abd", integrity(b"abc"), "artifact_digest_mismatch"),
    ],
)
def test_invalid_upload_never_reaches_storage(
    data: bytes, expected: ArtifactIntegrity, code: str
) -> None:
    client = Mock()
    with pytest.raises(ArtifactStorageError, match=code):
        GarageStorage(client, "private").put_verified(new_staging_key(), BytesIO(data), expected)
    client.put_object.assert_not_called()


@pytest.mark.parametrize("size", [-1, MAX_ARTIFACT_BYTES + 1])
def test_invalid_size(size: int) -> None:
    with pytest.raises(ArtifactStorageError, match="artifact_size_limit"):
        ArtifactIntegrity("0" * 64, size)


@pytest.mark.parametrize("digest", ["a", "A" * 64, "z" * 64])
def test_invalid_digest(digest: str) -> None:
    with pytest.raises(ArtifactStorageError, match="artifact_invalid_digest"):
        ArtifactIntegrity(digest, 0)


def test_upload_verifies_stored_bytes_and_uses_safe_metadata() -> None:
    body = BytesIO(b"abc")
    client = Mock()
    client.get_object.return_value = {"Body": body, "ContentLength": 3}
    key = new_staging_key()
    GarageStorage(client, "private").put_verified(key, BytesIO(b"abc"), integrity(b"abc"))
    assert client.put_object.call_args.kwargs == {
        "Bucket": "private",
        "Key": key,
        "Body": b"abc",
        "ContentLength": 3,
        "ContentType": "application/octet-stream",
        "ContentMD5": "kAFQmDzST7DWlj99KOF/cg==",
    }
    client.get_object.assert_called_once_with(Bucket="private", Key=key)
    assert body.closed
    assert new_staging_key() != key


@pytest.mark.parametrize(
    ("data", "length", "code"),
    [(b"abc", 4, "length"), (b"abd", 3, "digest"), (b"abcd", 3, "length")],
)
def test_corrupt_storage_closes_body(data: bytes, length: int, code: str) -> None:
    body = BytesIO(data)
    client = Mock()
    client.get_object.return_value = {"Body": body, "ContentLength": length}
    with pytest.raises(ArtifactStorageError, match=f"artifact_{code}_mismatch"):
        GarageStorage(client, "private").get_verified(new_staging_key(), integrity(b"abc"))
    assert body.closed


@pytest.mark.parametrize("operation", ["put", "get", "delete"])
def test_storage_failures_do_not_expose_endpoint_or_key(operation: str) -> None:
    client = Mock()
    for method in [client.put_object, client.get_object, client.delete_object]:
        method.side_effect = RuntimeError("secret endpoint and key")
    store = GarageStorage(client, "private")
    with pytest.raises(ArtifactStorageError, match="^artifact_storage_unavailable$") as error:
        if operation == "put":
            store.put_verified(new_staging_key(), BytesIO(b"abc"), integrity(b"abc"))
        elif operation == "get":
            store.get_verified(new_staging_key(), integrity(b"abc"))
        else:
            store.delete(new_staging_key())
    assert error.value.__suppress_context__


def test_invalid_storage_key_cannot_reach_s3() -> None:
    client = Mock()
    with pytest.raises(ArtifactStorageError, match="artifact_invalid_storage_key"):
        GarageStorage(client, "private").delete("other-prefix/key")
    client.delete_object.assert_not_called()


def test_client_uses_explicit_credentials_and_bounded_path_style() -> None:
    store = garage_storage(
        endpoint="http://127.0.0.1:3900",
        bucket="private",
        region="garage",
        access_key="test-key",
        secret_key="test-secret",
    )
    config: Any = store.client.meta.config
    assert config.signature_version == "s3v4"
    assert config.s3["addressing_style"] == "path"
    assert config.connect_timeout == 3
    assert config.read_timeout == 10
    assert config.retries["total_max_attempts"] == 2
    assert "test-secret" not in repr(store)
    store.client.close()
