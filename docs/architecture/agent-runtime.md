# Agent runtime

Hosted conversations belong to a project and retain private or explicitly shared messages, stable request IDs, ordered runs, durable events, leases, provider usage, cancellation, and recovery. Current membership and conversation control rights protect their routes.

A queued turn contains message text, a provider connection, and optional exact project artifact IDs. The context manifest contains artifact IDs and a canonical version-3 digest. It has no research revisions, public targets, or per-run research grants.

The builtin tool contract is `get_context`. Context returns the project and selected artifact metadata after reauthorization. The retired `project_files` tool is not advertised or executable. Git and Collaborative hosted execution keep their existing snapshot/worktree paths. Retired tool names are rejected even if an old token listed them.

Workers use authenticated internal APIs. Admission, bounded resource allocation, lease generations, execution slots, provider-request accounting, event cursors, and output limits remain enforced. Provider credentials stay behind the gateway. See [hosted controller](hosted-controller.md) and [failure handling](hosted-failures.md).

Completed hosted artifacts retain creator/conversation restrictions in addition to project membership. Generic project uploads commit after byte verification. There are no research proposal, revision-output, verification-job, or public contribution-run tables.

The removal migration revokes existing tool capabilities and removes verification scheduler work. Restart workers with the new code; existing interrupted work follows the ordinary lease/recovery policy.

New conversations default to version 3 of the built-in agent instructions, which describe project files. Historical versions remain immutable for existing conversation bindings. The agent picker advertises the current versions.
