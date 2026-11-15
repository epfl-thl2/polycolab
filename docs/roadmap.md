# Roadmap

The current product is a shared filesystem project workspace for humans and agents. Basic, Collaborative, and Git modes, hosted project conversations, artifacts, LaTeX builds, accounts, credentials, and the independent agent library remain implemented.

Release gates still require target-deployment verification of native hosted execution, provider integration, collaboration recovery, storage backups, and restoration. Local tests and deterministic providers do not establish those deployment properties.

External keys currently access Default files. Equivalent agent-key support for Git and Collaborative is not implemented. Direct provider chat has an API but no dedicated browser page.

The removed research-object database, commons, catalogue, publication, proposal reviews, and verification execution are outside the current scope. Reintroducing them would require a separate product decision.

## Unified sessions

The single session API, canonical conversation entities and typed transcripts,
paired historical migrations, shared contribution policy and browser history view
are implemented. Release acceptance must preserve IDs, causal transcript ordering,
run/event cursors, reservations, artifact references, runtime capabilities and
runtime bindings across PostgreSQL and SQLite. Browser and deterministic worker
gates cover shared participation, revocation, cancellation, reconnect, archival and
historical reads. Native Codex isolation, live provider behavior and target-deployment
acceptance remain separate gates; local deterministic tests do not establish them.

Release requires a maintenance cutover: stop admissions, drain or terminate active
work, stop writers, back up, migrate, deploy matching backend/browser/workers,
smoke-test, and reopen admissions. Rollback restores the matching backup and
application version.

ACP adapters, additional harnesses, autonomous subagent execution, forks, and
session deletion remain later work. Stored hierarchy and extensible identifiers
do not enable those operations.
