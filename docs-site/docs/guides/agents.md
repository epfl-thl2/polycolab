# Working with agents

Hosted conversations and external agents work within project permissions.

## Hosted conversations

When hosted execution is enabled, add a provider connection in **Settings → Provider connections**, open a project, and start a conversation. Choose **Codex** or **Base** using the combined harness/model picker in the composer footer. The compact button shows a harness icon and a friendly model label (or **Default** for the configured default). Its menu contains both harness and model connection choices. Codex must be available before you can send. Messages, runs, cancellation, and hosted artifacts stay associated with the conversation. Private conversations remain private unless explicitly shared with project members.

Agents can work on project files through the workspace's supported execution path. Review saved files and run results. Optional artifact IDs add project artifact metadata to a turn; they do not grant broader access.

## External agents

Use **Agent connect** to create a named agent API key and copy instructions for the current project. Keys currently support Basic files. They follow your current membership, so revoking a key or removing membership removes that access.

See the [connection guide](../setup/external-agent.md). Notes and research material belong in files; there is no separate research-object or publication workflow.

## Project conversations

Open a project and choose **New conversation** in the worktree panel. Select an
available agent and send a message. Configure your provider under **Settings → Model
providers** first. Choose the model connection in the composer for new and follow-up messages.
The conversation retains its agent configuration and exact execution references.
Queued and active turns show progress below the transcript. Tool calls and results are
grouped under expandable **Tool activity** rows. The composer stays available at the
bottom of the conversation; its send button becomes **Stop agent** while a turn runs.

Conversations start private. Their owner can open **Conversation actions (•••) → Sharing**, preview the visible
transcript and choose whether project members may read or editors may also
participate. Each participant uses their own provider connection and execution budget.
Sharing the transcript does not share private prompts, tool inputs or private output
artifacts. Membership and sharing changes apply to subsequent reads and worker actions.

Download artifacts from the latest completed run using the **Files** button in the
composer. These downloads are separate from project files. To view older outputs,
choose a run in **Files and run history**.

Use **Stop agent** for the displayed run, or open **Files and run history** to stop a
specific queued or active run. You can stop your own runs; the conversation owner can
stop any run in that conversation. Owners can also rename, archive and restore the
conversation. Archived conversations remain readable.

Older direct-chat conversations appear under **Settings → Saved chat history**.
They are read-only, with rename and archive controls. Unknown historical token counts
remain unknown, and reserved budgets are shown separately from recorded usage.

If your deployment provides shared models, the composer shows **Polycolab models** above **Your connections**. Choose one to chat without adding a personal API key. The configured default is selected automatically; changing the harness shows compatible shared models. Platform usage is subject to shared and per-user limits. The homepage research helper also offers the shared models enabled for that feature.

**Recents** lists saved conversations, not unfinished composers. In Basic and Collaborative projects, **New chat** returns to your unfinished composer and preserves its text. In the tabbed Git workspace, **New chat** reuses an empty chat tab; tabs containing unsent text remain separate. Sending the first message turns the composer into a conversation.
