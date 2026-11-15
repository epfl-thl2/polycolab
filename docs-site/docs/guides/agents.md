# Working with agents

Hosted conversations and external agents work within project permissions.

## Hosted conversations

When hosted execution is enabled, add a model provider in **Settings → Provider connections**, open a project, and start a conversation. Choose an available preset or supported custom prompt. Messages, runs, cancellation, and hosted artifacts stay associated with the session. Private conversations remain private unless explicitly shared with project members.

Agents can work on project files through the workspace's supported execution path. Review saved files and run results. Optional artifact IDs add project artifact metadata to a turn; they do not grant broader access.

## External agents

Use **Agent connect** to create a named agent key and copy instructions for the current project. Keys currently support Default files. They follow your current membership, so revoking a key or removing membership removes that access.

See the [connection guide](../setup/external-agent.md). Notes and research material belong in files; there is no separate research-object or publication workflow.

## Project conversations

Open a project and choose **New conversation** in the worktree panel. Select an
available agent and send a message. Configure your provider under **Settings → Model
providers** first. Follow-up messages use the provider selected in **Agent history**.
The conversation retains its agent configuration and exact execution references.

Conversations start private. Their owner can open **Sharing**, preview the visible
transcript and choose whether project members may read or contributors may also
participate. Each participant uses their own provider connection and execution budget.
Sharing the transcript does not share private prompts, tool inputs or private output
artifacts. Membership and sharing changes apply to subsequent reads and worker actions.

Use **Stop agent** for the displayed run, or open **Files and run history** to stop a
specific queued or active run. You can stop your own runs; the conversation owner can
stop any run in that conversation. Owners can also rename, archive and restore the
conversation. Archived conversations remain readable.

Older direct-chat conversations appear under **Settings → Saved chat history**.
They are read-only, with rename and archive controls. Unknown historical token counts
remain unknown, and reserved budgets are shown separately from recorded usage.
