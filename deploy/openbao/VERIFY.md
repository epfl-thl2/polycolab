# Live OpenBao verification

This opt-in gate uses an existing **disposable test key**, never application credential rows.
It starts no service and performs no key provisioning, rotation, deletion, policy changes or database migration.
Do not use a production key/token.

An operator must prepare the test key:

1. Provision a dedicated `polycolab-test-*` Transit key with the properties in [the adapter contract](README.md).
2. Rotate it once to create versions 1 and 2.
3. Keep both encryption/decryption versions available.

Adapt [the policy template](api-transit-policy.hcl) for that exact key.
Use a short-lived token restricted to metadata read and encrypt/decrypt.
The mount must be `transit`.
The endpoint must use HTTPS with a certificate trusted by the adapter.
The gate has no insecure-TLS or HTTP override.

Supply these values through the test process environment, not command arguments, committed files or diagnostic output:

- `POLYCOLAB_TEST_OPENBAO=1`
- `POLYCOLAB_TEST_OPENBAO_URL`: explicit HTTPS origin.
- `POLYCOLAB_TEST_OPENBAO_TOKEN`: restricted test token.
- `POLYCOLAB_TEST_OPENBAO_KEY`: dedicated `polycolab-test-*` key name.
- `POLYCOLAB_TEST_OPENBAO_BACKEND_ID`: non-secret stable test-backend label.

Run from the repository root:

```sh
uv run --directory backend pytest ../tests/execution/test_openbao_live.py -q
```

Do not enable HTTP wire logging or pytest local-variable dumps for credential tests.
An explicit opt-in with missing configuration fails rather than silently skipping.
Without opt-in all cases skip and no network connection is attempted.

The gate checks these conditions:

- Explicit version-1 wrapping and version-2 rewrapping.
- Unchanged encrypted payloads and continued old/new reads.
- Idempotent preparation.
- Owner/profile and environment isolation.
- Preservation after an unavailable-version failure.

The gate uses synthetic provider credentials and random owner/profile IDs.
The operator remains responsible for revoking the test token and retiring the disposable key according to its retention policy.

Include these values in the acceptance report:

- Exact server release and immutable image/package identity.
- Adapter commit and invocation result.
- TLS setup.
- Non-secret test-key policy.

This harness does not yet establish a tested reference release.
Passing it proves neither live AWS compatibility, database migration atomicity, token renewal, backup/restore, multi-node availability nor application/browser integration.
Those gates remain separate.
In particular, pre-provisioned versions test post-rotation compatibility, not a concurrent operator rotation drill.
