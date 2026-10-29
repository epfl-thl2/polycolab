# Connect an external agent

1. Open the intended project and choose **Agent connect**.
2. Create a named agent and API key, or select an existing agent. Account settings can reveal or revoke your keys.
3. Give your agent the connection instructions and configure the key in its private credential setting where available.
4. Ask it to read the served `/SKILL.md`, check `/api/v1/me`, and read the intended project.
5. Give it a specific task and file path. Review changes in the project's files.

Keys follow your current and future project memberships. They are not restricted to the project where the connection dialog was opened. Tell the agent which project to use and keep the credential out of files, logs, and public messages.

External keys currently support Default files. Read-only membership permits reads; active contributor or owner membership permits writes. Keys expire, have usage budgets, and can be revoked. They cannot manage accounts, members, credentials, or read conversations.

See [the developer guide](../developers/agent-runs.md) for request details.
