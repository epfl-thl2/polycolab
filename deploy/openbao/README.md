# OpenBao credential adapter

The API can select the dedicated `OpenBaoKeyWrapper` and `CredentialKeyring` through explicit application settings.
New writes use the configured OpenBao version, while an explicitly registered legacy AWS version remains readable.
Selecting OpenBao does not rewrite existing encrypted credentials.

For Transit rotation:

1. Set `OPENBAO_TRANSIT_VERSION` to the active writer.
2. Provide up to 32 unique positive prior versions in `OPENBAO_HISTORICAL_TRANSIT_VERSIONS`.
   Use a JSON array, for example, `[1,2]`.

The active version must not appear in that list.
Every entry registers the same explicit backend, environment, mount and key identity at that exact version.
Unregistered versions fail closed.
Keep historical readers until migration and restore evidence permits their removal.

## Key and deployment boundary

Provision an `aes256-gcm96` key with these properties:

- Derivation enabled.
- Convergence disabled.
- Export, plaintext backup, and deletion disabled.

The application identity may read exact key metadata and encrypt/decrypt only that key.
The accompanying `api-transit-policy.hcl` defines the reference policy for `transit/gateway`.
It grants no key creation, rotation, export, deletion, listing or policy administration.

The adapter supplies both derivation context and authenticated associated data.
Its context includes the original owner/profile binding, deployment environment, backend identity, mount and key name.
Its envelope identifier includes those operator-chosen labels and an explicit numeric Transit key version.
Encryption never silently selects the latest version.
The adapter checks metadata and the returned ciphertext version/shape before use.

Use TLS.
Supply an explicit, short-lived application credential.
The client ignores ambient proxies, never follows redirects and does not retry requests.
Responses are capped at 16 KiB.
Socket phases have three-second timeouts.
A ten-second elapsed-time check runs between response chunks.

This is not a hard DNS or total wall-clock deadline.
Loopback HTTP requires an explicit test-only opt-in.

The deployment must keep OpenBao configuration, unseal/recovery material and backups separate from the application database.
No root token, data key or API provider key belongs in browser/worker configuration or logs.
Key-service token refresh, TLS trust provisioning, audit-device setup and recovery drills remain deployment integration tasks, not capabilities supplied by this wrapper.

Protocol reference: [OpenBao Transit API](https://openbao.org/docs/api/secret/transit/) and [Transit key versioning](https://openbao.org/docs/secrets/transit/).
The reference setup has no pinned or tested live release/image digest.
Pin the selected release.
Verify it before claiming reference deployment acceptance.

## Non-destructive migration contract

`CredentialKeyring` chooses a reader by the exact stored envelope version.
It never tries alternative backends.
Register supported historical AWS wrappers under their unchanged historical version names while new writes use OpenBao.
Keep legacy readers and key versions available throughout migration and restore verification.
Legacy AWS records are not retroactively environment-bound until their new wrapping is committed.

`prepare_rewrap` verifies the old ciphertext, wraps the same data key with the target, verifies target unwrapping, and returns a candidate plus an expected source-envelope fingerprint.
It leaves the encrypted provider payload and the original envelope unchanged and performs no database writes.
A failure leaves the original record available to its old reader.

The persistence integration uses bounded snapshots and an audited atomic compare-and-swap operation:

1. Read a bounded page of profile IDs and exact encrypted envelopes.
   End the transaction before calling either key service.
2. Prepare each candidate outside the database transaction.
   Verify it outside the transaction.
3. Reauthorize the operation.
   Compare the stored source envelope under lock.
   Commit the replacement and audit/checkpoint record atomically only if the envelope still matches.
4. Skip already migrated records.
   Detect concurrent credential rotation.
   Retain old-key support on failures.
   Never place ciphertext or fingerprints in public DTOs or operational logs.
5. Exercise interruption/resume, mixed AWS/OpenBao reads, unavailable versions, concurrent rotation and restore before increasing minimum decryption versions.

The [operator command](MIGRATION.md) ends the read transaction before key-service work and invokes the atomic primitive per verified candidate.
Mock protocol/cryptography tests do not establish live AWS, OpenBao, or deployment verification.
