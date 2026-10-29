# Non-functional requirements

FastAPI owns authorization and canonical application metadata. Private workers use authenticated APIs and receive no database credentials.

Membership, archive state, and credential revocation are checked at protected boundaries. Files and conversations remain private even when project metadata is public. Authentication changes clear browser caches and drafts belonging to the previous account.

File saves detect concurrent edits. Default files use content digests; Git worktrees and Linear snapshots retain their own consistency contracts. Uncertain provider or file effects are not replayed silently.

Artifact bytes are verified against size and digest. Storage keys and provider secrets never appear in public responses. Hosted execution remains bounded by admission, lease, timeout, and resource limits.

Database upgrades use forward Alembic revisions with PostgreSQL and SQLite parity. Backups include the database, project files, artifacts, and required encryption keys. Tests distinguish mocked browser behavior, real local integration, and target-deployment acceptance.
