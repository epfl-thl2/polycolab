"""Opt-in Transit checks against an operator-provisioned disposable test key.

No provisioning, rotation, database writes, server startup or existing credentials.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from uuid import uuid4

import pytest

from polycolab.model_gateway.credentials import (
    CredentialError,
    credential_context,
    encrypt_credential,
)
from polycolab.model_gateway.migration import CredentialKeyring
from polycolab.model_gateway.openbao import OpenBaoKeyWrapper

pytestmark = pytest.mark.skipif(
    os.environ.get("POLYCOLAB_TEST_OPENBAO") != "1",
    reason="Set POLYCOLAB_TEST_OPENBAO=1 with an explicitly provisioned test key",
)


@pytest.fixture
def transit() -> Iterator[Callable[[int, str], OpenBaoKeyWrapper]]:
    # Suppress fixture locals, which contain the explicitly supplied test token.
    __tracebackhide__ = True
    prefix = "POLYCOLAB_TEST_OPENBAO_"
    names = ("URL", "TOKEN", "KEY", "BACKEND_ID")
    values = {name: os.environ.get(prefix + name, "") for name in names}
    if any(not value for value in values.values()):
        pytest.fail("OpenBao opt-in requires URL, TOKEN, KEY and BACKEND_ID", pytrace=False)
    if not values["KEY"].startswith("polycolab-test-"):
        pytest.fail("Use a dedicated polycolab-test-* key, never a production key", pytrace=False)
    with ExitStack() as stack:

        def make(version: int, environment: str = "integration") -> OpenBaoKeyWrapper:
            __tracebackhide__ = True
            try:
                wrapper = OpenBaoKeyWrapper(
                    base_url=values["URL"],
                    token=values["TOKEN"],
                    backend_id=values["BACKEND_ID"],
                    environment=environment,
                    key_name=values["KEY"],
                    transit_version=version,
                )
            except ValueError:
                pytest.fail("Invalid explicit OpenBao test configuration", pytrace=False)
            stack.callback(wrapper.close)
            return wrapper

        yield make


def test_live_versions_and_verified_rewrap(
    transit: Callable[[int, str], OpenBaoKeyWrapper],
) -> None:
    first, second = transit(1, "integration"), transit(2, "integration")
    context = credential_context(user_id=uuid4(), profile_id=uuid4())
    original = encrypt_credential(first, context=context, secret="synthetic-test-credential")
    assert original.wrapped_key.startswith(b"vault:v1:")
    keyring = CredentialKeyring([first, second])
    candidate = keyring.prepare_rewrap(
        context=context, encrypted=original, target_version=second.key_version
    )
    assert candidate.encrypted.wrapped_key.startswith(b"vault:v2:")
    assert candidate.encrypted.ciphertext == original.ciphertext
    for envelope in (original, candidate.encrypted):
        assert keyring.decrypt(context=context, encrypted=envelope) == "synthetic-test-credential"
    # Retry is non-destructive and recognizes an already migrated envelope.
    retry = keyring.prepare_rewrap(
        context=context, encrypted=candidate.encrypted, target_version=second.key_version
    )
    assert retry.encrypted == candidate.encrypted


@pytest.mark.parametrize("changed", ["user", "profile", "environment"])
def test_live_context_isolation(
    transit: Callable[[int, str], OpenBaoKeyWrapper], changed: str
) -> None:
    user, profile = uuid4(), uuid4()
    context = credential_context(user_id=user, profile_id=profile)
    wrapper = transit(1, "integration")
    encrypted = encrypt_credential(wrapper, context=context, secret="synthetic-test-credential")
    other_context = credential_context(
        user_id=uuid4() if changed == "user" else user,
        profile_id=uuid4() if changed == "profile" else profile,
    )
    other_wrapper = transit(1, "other-environment") if changed == "environment" else wrapper
    # Exercise Transit directly rather than stopping at envelope-version routing.
    with pytest.raises(CredentialError):
        other_wrapper.unwrap(encrypted.wrapped_key, other_context)
    assert (
        CredentialKeyring([wrapper]).decrypt(context=context, encrypted=encrypted)
        == "synthetic-test-credential"
    )


def test_live_unavailable_version_preserves_original(
    transit: Callable[[int, str], OpenBaoKeyWrapper],
) -> None:
    first, absent = transit(1, "integration"), transit(2**31 - 1, "integration")
    context = credential_context(user_id=uuid4(), profile_id=uuid4())
    original = encrypt_credential(first, context=context, secret="synthetic-test-credential")
    keyring = CredentialKeyring([first, absent])
    with pytest.raises(CredentialError, match="key_service_policy_invalid"):
        keyring.prepare_rewrap(
            context=context, encrypted=original, target_version=absent.key_version
        )
    assert keyring.decrypt(context=context, encrypted=original) == "synthetic-test-credential"
