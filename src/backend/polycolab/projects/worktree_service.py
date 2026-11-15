"""Shared-worktree policy, optimistic revisions, and recoverable mutations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from uuid import UUID, uuid4, uuid5

import structlog

from polycolab.access.authorization import ProjectAction, project_policy
from polycolab.entities.repositories import RepositoryError, RepositoryReceipt, Worktree
from polycolab.entities.time import utc_now
from polycolab.projects.git_storage import ZERO, branch_name
from polycolab.projects.repository_service import RepositoryService
from polycolab.projects.worktree_storage import WorktreeStorage


class WorktreeService(RepositoryService):
    @property
    def files(self) -> WorktreeStorage:
        return WorktreeStorage(self.git)

    def materialize(self, *, provision_empty: bool = False) -> None:
        """Resumable rollout, under the repository lock; preserves all old IDs."""
        self.authorize(not provision_empty)
        if self.store.project_active(self.project_id):
            raise RepositoryError("worktree_runs_must_be_drained")
        worktrees = self.store.worktrees(self.project_id, True)
        for worktree in worktrees:
            if self.store.branch_active(self.project_id, worktree.branch):
                raise RepositoryError("worktree_runs_must_be_drained")
        branches = self.git.branches()
        known = {worktree.branch for worktree in worktrees}
        for branch in branches:
            if branch in known:
                continue
            now = utc_now()
            worktree = Worktree(
                UUID(branch[9:])
                if branch.startswith("sessions/")
                else uuid5(self.project_id, branch),
                self.project_id,
                "Main" if branch == "main" else "Saved working copy",
                branch,
                self.user_id,
                now,
                now,
                None,
            )
            self.store.create_worktree(worktree)
            worktrees.append(worktree)
        self.transaction.commit()
        for worktree in worktrees:
            if worktree.removed_at is None:
                self.files.initialize(worktree.id, worktree.branch)
        self.store.activate_native(self.project_id)
        self.transaction.commit()

    def ensure_native(self) -> None:
        if self.store.native(self.project_id):
            return
        access = project_policy.require_scope(
            self.transaction, self.project_id, self.user_id, ProjectAction.VIEW
        )
        if access.project.file_mode != "git":
            raise RepositoryError("git_archive_unavailable", 404)
        # A fresh repository can be provisioned with its first worktree request.
        if len(self.git.history(self.git.head("main"), 2)) == 1 and not self.store.worktrees(
            self.project_id, True
        ):
            self.materialize(provision_empty=True)
        else:
            raise RepositoryError("worktree_migration_required")

    def worktree_for_branch(self, branch: str) -> Worktree:
        for worktree in self.store.worktrees(self.project_id, True):
            if worktree.branch == branch:
                return worktree
        raise RepositoryError("worktree_not_found", 404)

    def require_available(self, worktree: Worktree) -> str:
        if worktree.removed_at is not None:
            raise RepositoryError("worktree_removed")
        if not self.files.available(worktree.id, worktree.branch):
            raise RepositoryError("worktree_unavailable", 503)
        revision = self.files.revision(worktree.id)
        if self.files.snapshot_head(revision) != self.git.head(worktree.branch):
            raise RepositoryError("worktree_external_head_change", 409)
        return revision

    def state(self, worktree: Worktree) -> dict[str, object]:
        available = worktree.removed_at is None and self.files.available(
            worktree.id, worktree.branch
        )
        revision = self.files.revision(worktree.id) if self.files.exists(worktree.id) else None
        head = self.git.head(worktree.branch)
        committed = self.git.entries(head)
        saved = self.git.entries(revision) if revision else committed
        changed = [
            {
                "path": path,
                "status": "added"
                if path not in committed
                else "deleted"
                if path not in saved
                else "modified",
            }
            for path in sorted(saved.keys() | committed.keys())
            if saved.get(path) != committed.get(path)
        ]
        return {
            **{name: getattr(worktree, name) for name in worktree.__dataclass_fields__},
            "head_commit": head,
            "revision": revision,
            "lifecycle": "removed"
            if worktree.removed_at
            else "active"
            if available
            else "unavailable",
            "changed_files": changed,
            "ignored_files": sorted(self.files.ignored_files(worktree.id) & saved.keys())
            if available
            else [],
            "files": [
                {"path": path, "size": item[2], "executable": item[0] == "100755"}
                for path, item in saved.items()
            ],
            "writable": available
            and project_policy.require_scope(
                self.transaction, self.project_id, self.user_id, ProjectAction.VIEW
            ).project.file_mode
            == "git"
            and not self.transaction.collaborative.conversion_pending(self.project_id)
            and project_policy.can(
                self.transaction, self.project_id, self.user_id, ProjectAction.WRITE_FILES
            )
            and not self.store.branch_active(self.project_id, worktree.branch),
        }

    def mutate_worktree(
        self,
        worktree: Worktree,
        expected: str,
        key: str,
        payload: object,
        prepare: Callable[[], tuple[str, str]],
        authority: Callable[[], None] | None = None,
    ) -> str:
        """Caller holds the repository lock. Prepare returns (tree, branch head)."""
        authorize = authority or (lambda: self.authorize(True, worktree.branch))
        authorize()
        self.transaction.commit()
        digest = hashlib.sha256(
            json.dumps(
                {"worktree_id": str(worktree.id), "payload": payload},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        receipt = self.store.receipt(self.project_id, self.user_id, key)
        # Git preparation may take time. Do not retain a SQLite read snapshot
        # across it and then attempt to promote that stale snapshot to a writer.
        self.transaction.commit()
        if receipt:
            if receipt.digest != digest or receipt.branch != worktree.branch:
                raise RepositoryError("repository_retry_mismatch")
            if receipt.completed or self.files.contains(worktree.id, receipt.new_commit):
                self.store.complete(receipt.id)
                self.transaction.commit()
                return receipt.new_commit
        else:
            if self.require_available(worktree) != expected:
                raise RepositoryError("worktree_stale_revision")
            tree, head = prepare()
            revision = self.files.snapshot(worktree.id, tree, head, expected)
            receipt = RepositoryReceipt(
                uuid4(),
                self.project_id,
                self.user_id,
                key,
                digest,
                worktree.branch,
                expected,
                revision,
                False,
                utc_now(),
            )
            self.store.prepare(receipt)
            self.transaction.commit()
        authorize()
        if self.require_available(worktree) != receipt.old_commit:
            raise RepositoryError("worktree_stale_revision")
        self.files.apply(worktree.id, worktree.branch, receipt.new_commit)
        self.store.complete(receipt.id)
        self.transaction.commit()
        structlog.get_logger().info(
            "worktree_operation_applied",
            operation_id=str(receipt.id),
            project_id=str(self.project_id),
            worktree_id=str(worktree.id),
        )
        return receipt.new_commit

    def change(
        self,
        identifier: UUID,
        expected: str,
        key: str,
        operation: str,
        payload: object,
        changes: dict[str, bytes | None] | None = None,
        message: str = "",
    ) -> str:
        with self.open():
            self.ensure_native()
            worktree = self.store.worktree(self.project_id, identifier)

            def prepare() -> tuple[str, str]:
                head = self.git.head(worktree.branch)
                if operation == "save":
                    return self.git.changed_tree(expected, changes or {}), head
                if operation == "discard":
                    return self.git.git("rev-parse", f"{head}^{{tree}}").decode().strip(), head
                if not message.strip():
                    raise RepositoryError("worktree_commit_message_required", 422)
                if self.files.clean(worktree.id, worktree.branch):
                    raise RepositoryError("worktree_nothing_to_commit")
                tree = self.git.git("rev-parse", f"{expected}^{{tree}}").decode().strip()
                return tree, self.git.commit_tree(tree, [head], message.strip(), str(self.user_id))

            return self.mutate_worktree(worktree, expected, key, payload, prepare)

    def create_worktree(self, identifier: UUID, title: str, branch: str, start: str) -> Worktree:
        with self.open():
            self.ensure_native()
            self.authorize(True)
            branch_name(branch)
            digest = hashlib.sha256(json.dumps([title, branch, start]).encode()).hexdigest()
            key = f"create-worktree-{identifier}"
            receipt = self.store.receipt(self.project_id, self.user_id, key)
            if receipt and receipt.digest != digest:
                raise RepositoryError("worktree_retry_mismatch")
            existing = None
            for worktree in self.store.worktrees(self.project_id, True):
                if worktree.id == identifier:
                    if (worktree.title, worktree.branch, worktree.created_by_user_id) != (
                        title,
                        branch,
                        self.user_id,
                    ):
                        raise RepositoryError("worktree_retry_mismatch")
                    existing = worktree
                elif worktree.branch == branch:
                    raise RepositoryError("worktree_branch_exists")
            if existing is None:
                if self.git.head(branch, missing=True):
                    raise RepositoryError("worktree_branch_exists")
                if self.store.worktree_identifier_taken(identifier):
                    raise RepositoryError("worktree_not_found", 404)
                head = self.git.head(start)
                now = utc_now()
                existing = Worktree(
                    identifier, self.project_id, title, branch, self.user_id, now, now, None
                )
                receipt = RepositoryReceipt(
                    uuid4(),
                    self.project_id,
                    self.user_id,
                    key,
                    digest,
                    branch,
                    head,
                    head,
                    False,
                    now,
                )
                self.store.prepare(receipt)
                self.store.create_worktree(existing)
                self.transaction.commit()
            if existing.removed_at:
                return existing
            self.authorize(True, branch)
            if not self.git.head(branch, missing=True):
                if receipt is None:
                    raise RepositoryError("worktree_unavailable", 503)
                self.git.advance(branch, ZERO, receipt.new_commit)
            self.files.initialize(identifier, branch)
            if receipt:
                self.store.complete(receipt.id)
            self.transaction.commit()
            return existing

    def rename_worktree(self, identifier: UUID, title: str) -> Worktree:
        with self.open():
            self.ensure_native()
            access = project_policy.require_scope(
                self.transaction, self.project_id, self.user_id, ProjectAction.WRITE_FILES
            )
            if (
                access.project.file_mode != "git"
                or self.transaction.collaborative.conversion_pending(self.project_id)
            ):
                raise RepositoryError("git_workspace_read_only")
            self.store.worktree(self.project_id, identifier, lock=True)
            updated = self.store.update_worktree(identifier, title, None)
            self.transaction.commit()
            return updated

    def lifecycle(
        self,
        identifier: UUID,
        *,
        removed: bool,
        discard: bool = False,
        title: str | None = None,
        expected: str | None = None,
    ) -> Worktree:
        with self.open():
            self.ensure_native()
            worktree = self.store.worktree(self.project_id, identifier, lock=True)
            self.authorize(True)
            if self.store.branch_active(self.project_id, worktree.branch):
                raise RepositoryError("worktree_active")
            if removed:
                if (
                    expected
                    and worktree.removed_at is None
                    and self.files.revision(identifier) != expected
                ):
                    raise RepositoryError("worktree_stale_revision")
                if worktree.branch == "main":
                    raise RepositoryError("worktree_main_cannot_remove")
                if (
                    self.files.exists(identifier)
                    and not self.files.clean(identifier, worktree.branch)
                    and not discard
                ):
                    raise RepositoryError("worktree_discard_confirmation_required")
                # SQL tombstone first: a crash can leave a checkout, never expose it as active.
                updated = self.store.update_worktree(identifier, title, True)
                self.transaction.commit()
                self.files.remove(identifier, worktree.branch)
            else:
                if worktree.removed_at:
                    self.files.restore(identifier, worktree.branch)
                elif not self.files.available(identifier, worktree.branch):
                    self.files.apply(
                        identifier, worktree.branch, self.files.revision(identifier), create=True
                    )
                updated = self.store.update_worktree(identifier, title, False)
                self.transaction.commit()
            return updated
