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

## Platform model catalog

`POLYCOLAB_MODEL_CONFIG` selects an operator-owned YAML catalog of providers, models, and defaults. Provider keys are resolved from named environment variables at startup. Models have stable catalog IDs and deterministic internal connection IDs. Project-chat entries are synchronized into platform-owned provider connections with no user owner, encrypted credentials, and versioned routing/policy snapshots. Runs retain their connection reference and resolved upstream model ID. Removing a catalog entry disables its connection; running without a catalog denies all platform connections even if old rows remain; changing its routing, key, or policy invalidates outstanding grants. Account credential-management endpoints remain owner-only and cannot edit platform connections.

Authenticated `GET /api/v1/platform-models` returns labels, IDs, uses, defaults, and harness compatibility, never credential previews or provider endpoints. The composer groups platform models separately from personal connections and prefers the configured project default. Compatibility also reflects the configured executor protocol. The research helper accepts an optional catalog model ID and otherwise uses its configured default. Legacy single-helper environment settings remain a compatibility fallback.

Catalog project runs retain existing per-user/project admission limits. All catalog models share a UTC daily cost reservation in `execution_rate_windows`, admitted atomically before execution or helper dispatch. Project reservations cover all possible rounds and attempts; helper reservations bound input bytes and output tokens. Reservations remain charged on failure and are not refunded, so the ceiling is conservative rather than an actual-spend report. Current-day budget rows are excluded from minute-counter cleanup. Configured global price ceilings must cover every project model for existing user/project budget calculations.

## Credential handling

Provider connections never return the full API key, ciphertext, or wrapped data key.
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

The human-only `POST /api/v1/research-helper/messages` endpoint provides project-independent, text-only research assistance using a shared model configured by the platform operator. It accepts no personal provider connection selection. It supports Chat Completions and Responses endpoints, keeps the platform credential on the server, and sends a fixed research-assistant system prompt without tools. It does not read project data or persist transcripts. Provider requests disable stored responses; provider retention policies still apply.

Catalog helper turns also participate in the shared admission budget; they do not create agent runs. Helper requests accept at most 31 alternating user/assistant messages totaling 48,000 UTF-8 bytes and cap output at 2,048 tokens. The existing IP-pinned transport bounds request/response size and timeouts, rejects unsafe destinations, and performs no retries for helper requests. Durable per-user and global minute counters admit each request before provider I/O, including failed requests. These counters bound request volume; helper turns are not agent runs and do not participate in the agent-run usage ledger.

Provider base URLs reject insecure schemes outside local development, credentialed URLs, private or metadata addresses, unsafe DNS answers, redirects, and proxy-environment routing.
Connections use a vetted public IP while preserving the original HTTP host and TLS identity.

Validation and inference requests have finite connection, read, write, pool, retry, byte, event, token, and cost bounds.
Polycolab normalizes and records usage.
Ambiguous I/O and provider 5xx responses are not replayed.
Unpriced non-local configurations fail closed.

Live KMS/Transit policy, DNS and egress controls, and real-provider conformance require **Deployment verification**.
Local tests cover envelope encryption, redaction, one-use grants, SSRF policy, bounded transport, and stable failure mapping.
