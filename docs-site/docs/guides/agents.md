# Working with agents

Hosted conversations and external agents work within project permissions.

## Hosted conversations

When hosted execution is enabled, add a model provider in **Settings → Model providers**, open a project, and start a conversation. Choose an available preset or supported custom prompt. Messages, runs, cancellation, and hosted artifacts stay associated with the session. Private conversations remain private unless explicitly shared with project members.

Agents can work on project files through the workspace's supported execution path. Review saved files and run results. Optional artifact IDs add project artifact metadata to a turn; they do not grant broader access.

## External agents

Use **Agent connect** to create a named agent key and copy instructions for the current project. Keys currently support Default files. They follow your current membership, so revoking a key or removing membership removes that access.

See the [connection guide](../setup/external-agent.md). Notes and research material belong in files; there is no separate research-object or publication workflow.
