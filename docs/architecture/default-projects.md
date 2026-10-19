# Default projects

Default stores current files on the server without version control.
Existing projects keep their mode. API callers that omit `workspace_mode` retain
the Git default for compatibility. No database migration is needed: the existing
mode column accepts `default`, `linear`, and `git`.

## Files and access

Each Default project stores its current files at
`PROJECT_REPOSITORY_DIRECTORY/<project UUID>.files/` on the API server volume.
There is no Git repository, operation log, checkpoint, tombstone, or retained file
revision. Project metadata, membership, conversations, and research records remain
in the database. Research version and publication rules are unchanged.

The member-only `/api/v1/projects/{project_id}/files` API lists files and accepts
read, write, rename, and delete commands. Paths are relative; traversal, symlinks,
Git internals, and nonregular files are rejected. A project filesystem lock
serializes commands. Writes stage bytes outside the project and atomically replace
the destination. A content digest checks that a changed file still matches the
caller's last read; it does not retain an earlier version. Stale saves return a
conflict. Creating a file requires an unused path; rename never replaces another
file. Files are limited to 700 KB, 2,000 files, and the configured project byte quota.

Owners and contributors can edit; read-only members can inspect. Outsiders cannot
read project files, including files in public projects. Archived projects reject
writes. Backup the current project volume alongside the database.

## Agents

Private Default conversations expose the `project_files` tool through the existing
authenticated tool gateway. It reads and writes the same current server files with
the same digest checks and current membership checks. Mutations apply immediately;
there is no batch merge, revert, or checkpoint. The existing run capability and
lease checks apply. Public-destination runs cannot access these files.

Default files are not automatically mounted in a hosted execution directory.
An agent uses `project_files` to read inputs and save outputs; shell commands act
on its isolated execution directory. No repository binding or Git bundle is
created for a Default run. Conversation and tool event records remain part of the
existing agent system, independently of filesystem versioning.
