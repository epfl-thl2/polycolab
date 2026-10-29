# Agent interface

Humans and agents work on the same project files. External agents authenticate with human-issued `pca_` credentials. Hosted agents authenticate through private worker and run capabilities.

External keys can list member projects and read Default files under current membership. Owners and contributors can authorize writes; read-only membership cannot. Every request rechecks revocation, expiry, remaining budgets, project state, and membership. Keys do not permit account, membership, or credential administration and do not expose conversations.

Default file updates use the digest returned by the last read. A conflicting edit must be compared with the current file rather than overwritten. External keys currently do not grant Git or Linear HTTP access.

Hosted sessions retain private messages, explicitly shared conversation access, execution limits, cancellation, and artifacts. Their tools expose project file operations and explicitly selected project artifact metadata. Removed research tools and old capabilities do not grant authority.

See the [external API contract](../architecture/external-agent-api.md) and [runtime contract](../architecture/agent-runtime.md).
