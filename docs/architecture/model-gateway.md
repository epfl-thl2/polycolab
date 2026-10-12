# Model Gateway

The Model Gateway is a security-critical logical module inside the Application API.
It protects model-provider credentials and mediates bounded inference.
It is not a separate deployable.
Workers receive a one-use run grant and normalized model events, never a stored credential.

New profiles default to the Responses protocol.
Migration preserves existing profiles as Chat Completions.
Validation uses the declared protocol.
The disabled [hosted controller candidate](hosted-controller.md) uses a private bounded native Responses endpoint and records provider usage or conservative failure estimates.
The legacy normalized model endpoint remains for the existing worker.

## Credential handling

Provider profiles never return the full API key, ciphertext, or wrapped data key.
They return an owner-only `api_key_preview`, saved atomically when a key is created or replaced.
For keys of at least 12 characters, it contains the first three and last four characters separated by four bullets.
Keys of 5–11 characters show four bullets and the last four characters; shorter keys show only four bullets.
Existing profiles retain a null preview until key replacement; reads never decrypt credentials to produce previews.
Credential rewrapping preserves the preview, and provider deletion clears it.
Non-local deployments select AWS KMS or OpenBao Transit.
OpenBao writes use an explicit environment/backend/key/version identity and authenticated context.
A bounded list of prior Transit versions and an optional exact-version AWS reader support rotation/migration without trial decryption.
Unregistered versions fail closed.
Only local development and tests permit local AES-GCM.

Credential rewrap reads bounded profile snapshots without locks.
All key service work occurs after that read transaction ends.
Before committing, rewrap locks and matches the exact owner, credential version and source-envelope fingerprint.
The replacement and private immutable audit record commit atomically.
No public DTO exposes migration fingerprints or encrypted material.
Orchestration and live key rotation/restore verification remain deployment work.

## Network and usage policy

Provider base URLs reject insecure schemes outside local development, credentialed URLs, private or metadata addresses, unsafe DNS answers, redirects, and proxy-environment routing.
Connections use a vetted public IP while preserving the original HTTP host and TLS identity.

Validation and inference requests have finite connection, read, write, pool, retry, byte, event, token, and cost bounds.
Polycolab normalizes and records usage.
Ambiguous I/O and provider 5xx responses are not replayed.
Unpriced non-local configurations fail closed.

Live KMS/Transit policy, DNS and egress controls, and real-provider conformance require **Deployment verification**.
Local tests cover envelope encryption, redaction, one-use grants, SSRF policy, bounded transport, and stable failure mapping.
