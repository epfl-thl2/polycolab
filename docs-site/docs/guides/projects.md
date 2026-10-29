# Projects and access

A project groups shared files, members, and conversations. Owners manage settings and membership. Contributors can edit files; read-only members can inspect them. Archiving stops writes until an owner restores the project.

## File modes

| Mode    | Behavior                                                                                |
| ------- | --------------------------------------------------------------------------------------- |
| Default | Current files in a server directory, with conflict checks and no version history        |
| Linear  | Shared live editing, saved checkpoints, and agent changes reconciled with current files |
| Git     | Worktrees, saved edits, explicit commits, and branch comparison                         |

Project conversations use the selected workspace. LaTeX builds operate on saved files where supported. File previews and editors retain drafts when switching tabs; resolve conflicting saves by comparing current contents.

## Visibility

Public projects expose their name and description in the directory. Members are required to read files and artifacts. Conversations retain private or explicitly shared access. Private projects are visible only to their members.

Changing visibility does not publish file contents. Project names and descriptions should be suitable for the chosen visibility.
