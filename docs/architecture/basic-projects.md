# Basic projects

Basic is the browser's initial choice for new projects.
Existing projects keep their mode. API callers that omit `file_mode` retain
the Git default for compatibility. The `file_mode` column accepts `basic`, `collaborative`, and `git`.

## Files and access

Each Basic project stores its current files at
`PROJECT_REPOSITORY_DIRECTORY/<project UUID>.files/` on the API server volume.
There is no Git repository, operation log, checkpoint, tombstone, or retained file
revision. Project metadata, membership, conversations, and artifact metadata remain
in the database.

The member-only `/api/v1/projects/{project_id}/files` API lists files and accepts
read, write, rename, and delete commands. Paths are relative; traversal, symlinks,
Git internals, and nonregular files are rejected. A project filesystem lock
serializes commands. Writes stage bytes outside the project and atomically replace
the destination. A content digest checks that a changed file still matches the
caller's last read; it does not retain an earlier version. Stale saves return a
conflict. Creating a file requires an unused path; rename never replaces another
file. Files are limited to 700 KB, 2,000 files, and the configured project byte quota.

Owners and editors can edit; viewers can inspect. Outsiders cannot
read project files, including files in public projects. Archived projects reject
writes. Backup the current project volume alongside the database.

The same endpoints accept external agent API keys. Account keys follow their owner's
current project membership; project-bound keys additionally require a matching
project ID. Agents cannot use these endpoints to manage membership or access Git
or Collaborative files. Keys must remain unexpired and unrevoked. The service rechecks
key authority under the project/membership and filesystem locks before file I/O.

Authenticated agent requests consume the key's request limit. Mutating commands
also reserve one mutation before filesystem I/O, so conflicts, failed commands,
and ambiguous writes consume that reservation. Reads do not consume mutation
budget. Writes use the same expected-digest checks, path restrictions and quotas
as human edits. Responses are private and non-cacheable.

## Browser

Basic uses the shared project shell, logo, navigation, chat center, and resizable
side panels. Chats and Files in the navigation rail select the left panel: either
a New chat action with an icon above a scrolling Recents list, or the file tree
with creation and upload controls. Recents includes drafts and accessible shared conversations.
The project name opens an information modal. Overview is not a rail destination in this mode. The right panel has a white background and
shows files; the chat agent-history panel is hidden. Opening a file selects the right sidebar’s File view
while the conversation stays in the center. The compact editor toolbar is shared
with Git; new files use an inline path field with Enter to create and Escape to
cancel. There are no document tabs or file-history controls.
Files support creation, upload, explicit save, download, rename, and deletion.
Unsaved edits block opening another file or leaving the project and remain visible
after a save conflict. Switching conversations, sidebar views, or mobile drawers
retains the mounted editor and its draft. Reload
fetches current bytes; it does not merge concurrent edits. Basic does not use
Collaborative's Yjs collaboration service.

## Agents

Basic hosted conversations expose `get_context` for authorized project and artifact
metadata. The `project_files` model tool is removed; calls to that retired name are
rejected, including calls using previously issued capabilities.

Basic files are not automatically mounted in a hosted execution directory.
Shell commands act on the isolated execution directory; they do not update Basic
project files. Automatic `/workspace` snapshot and save-back support is unfinished
and tracked in the roadmap. The guarded file API remains available to humans and
external agents with authorized API keys.
