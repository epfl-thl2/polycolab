# Essential product qualities

These rules support the core [features](functional.md) and [interactions](human-interface.md).
Implementation and operational details belong in the [architecture](../architecture/README.md) and [deployment guide](../../deploy/README.md).

## Research integrity

- Saved research retains stable identities, immutable revisions, authorship, and source references.
- Relationships and evidence identify exact revisions.
- Conflicting edits must not overwrite newer work silently.
- Retrying a completed action must not create duplicate contributions or decisions.
- Endorsement, formal checking, and computational support remain separate properties.

## Permissions and privacy

- The server enforces current permissions for sensitive reads and writes.
- Private research, conversations, activity, and credentials must not leak through public views, search, errors, or summaries.
- Agents act only within granted scope and the sponsor's current permissions.
- Revocation prevents further authorized work.
- Public publication requires an explicit human action and must exclude private context and secrets.

## Safe execution

- Agent work and Lean/Python jobs have finite resource and time limits.
- Executable research runs in isolation from trusted service processes and credentials.
- Results preserve their inputs and environment so researchers can inspect and reproduce the work.
- Cancellation and failure states explain whether work can continue or must restart.

## Usability and recovery

- Core actions support keyboard use and small screens.
- Mathematical content remains readable through documents and lists without depending on a graph.
- Status and permission differences must not depend only on color.
- Errors offer a safe next action without exposing private data.
- Drafts survive navigation or require confirmation before discard.
- Reconnecting lets users resume saved conversations and inspect committed results.

## Performance and capacity

Search, lists, history, and relationship exploration must remain usable as research grows.
Load supporting content as needed rather than fetching the entire project.
Long-running work shows progress and does not block ordinary reading or editing.
