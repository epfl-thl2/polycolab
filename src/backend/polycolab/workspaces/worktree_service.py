"""Shared-worktree policy, optimistic revisions, and recoverable mutations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from uuid import UUID, uuid4, uuid5

import structlog

from polycolab.access.authorization import WorkspaceAction, workspace_policy
from polycolab.entities.repositories import RepositoryError, RepositoryReceipt, WorkspaceTask
from polycolab.entities.time import utc_now
from polycolab.workspaces.git_storage import ZERO, branch_name
from polycolab.workspaces.repository_service import RepositoryService
from polycolab.workspaces.worktree_storage import WorktreeStorage


class WorktreeService(RepositoryService):
    @property
    def files(self) -> WorktreeStorage:
        return WorktreeStorage(self.git)

    def materialize(self, *, provision_empty: bool = False) -> None:
        """Resumable rollout, under the repository lock; preserves all old IDs."""
        self.authorize(not provision_empty)
        if self.store.workspace_active(self.workspace_id):
            raise RepositoryError("worktree_runs_must_be_drained")
        tasks = self.store.tasks(self.workspace_id, True)
        for task in tasks:
            if self.store.branch_active(self.workspace_id, task.branch):
                raise RepositoryError("worktree_runs_must_be_drained")
        branches = self.git.branches()
        known = {task.branch for task in tasks}
        for branch in branches:
            if branch in known:
                continue
            now = utc_now()
            task = WorkspaceTask(
                UUID(branch[9:])
                if branch.startswith("sessions/")
                else uuid5(self.workspace_id, branch),
                self.workspace_id,
                "Main" if branch == "main" else "Saved working copy",
                branch,
                self.user_id,
                now,
                now,
                None,
            )
            self.store.create_task(task)
            tasks.append(task)
        self.transaction.commit()
        for task in tasks:
            if task.archived_at is None:
                self.files.initialize(task.id, task.branch)
        self.store.activate_native(self.workspace_id)
        self.transaction.commit()

    def ensure_native(self) -> None:
        if self.store.native(self.workspace_id):
            return
        # A fresh repository can be provisioned with its first worktree request.
        if len(self.git.history(self.git.head("main"), 2)) == 1 and not self.store.tasks(
            self.workspace_id, True
        ):
            self.materialize(provision_empty=True)
        else:
            raise RepositoryError("worktree_migration_required")

    def task_for_branch(self, branch: str) -> WorkspaceTask:
        for task in self.store.tasks(self.workspace_id, True):
            if task.branch == branch:
                return task
        raise RepositoryError("worktree_not_found", 404)

    def require_available(self, task: WorkspaceTask) -> str:
        if task.archived_at is not None:
            raise RepositoryError("worktree_removed")
        if not self.files.available(task.id, task.branch):
            raise RepositoryError("worktree_unavailable", 503)
        revision = self.files.revision(task.id)
        if self.files.snapshot_head(revision) != self.git.head(task.branch):
            raise RepositoryError("worktree_external_head_change", 409)
        return revision

    def state(self, task: WorkspaceTask) -> dict[str, object]:
        available = task.archived_at is None and self.files.available(task.id, task.branch)
        revision = self.files.revision(task.id) if self.files.exists(task.id) else None
        head = self.git.head(task.branch)
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
            **{name: getattr(task, name) for name in task.__dataclass_fields__},
            "head_commit": head,
            "revision": revision,
            "lifecycle": "removed"
            if task.archived_at
            else "active"
            if available
            else "unavailable",
            "changed_files": changed,
            "ignored_files": sorted(self.files.ignored_files(task.id) & saved.keys())
            if available
            else [],
            "files": [
                {"path": path, "size": item[2], "executable": item[0] == "100755"}
                for path, item in saved.items()
            ],
            "writable": available
            and workspace_policy.can(
                self.transaction, self.workspace_id, self.user_id, WorkspaceAction.CREATE_RESEARCH
            )
            and not self.store.branch_active(self.workspace_id, task.branch),
        }

    def mutate_worktree(
        self,
        task: WorkspaceTask,
        expected: str,
        key: str,
        payload: object,
        prepare: Callable[[], tuple[str, str]],
        authority: Callable[[], None] | None = None,
    ) -> str:
        """Caller holds the repository lock. Prepare returns (tree, branch head)."""
        authorize = authority or (lambda: self.authorize(True, task.branch))
        authorize()
        self.transaction.commit()
        digest = hashlib.sha256(
            json.dumps(
                {"worktree_id": str(task.id), "payload": payload},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        receipt = self.store.receipt(self.workspace_id, self.user_id, key)
        if receipt:
            if receipt.digest != digest or receipt.branch != task.branch:
                raise RepositoryError("repository_retry_mismatch")
            if receipt.completed or self.files.contains(task.id, receipt.new_commit):
                self.store.complete(receipt.id)
                self.transaction.commit()
                return receipt.new_commit
        else:
            if self.require_available(task) != expected:
                raise RepositoryError("worktree_stale_revision")
            tree, head = prepare()
            revision = self.files.snapshot(task.id, tree, head, expected)
            receipt = RepositoryReceipt(
                uuid4(),
                self.workspace_id,
                self.user_id,
                key,
                digest,
                task.branch,
                expected,
                revision,
                False,
                utc_now(),
            )
            self.store.prepare(receipt)
            self.transaction.commit()
        authorize()
        if self.require_available(task) != receipt.old_commit:
            raise RepositoryError("worktree_stale_revision")
        self.files.apply(task.id, task.branch, receipt.new_commit)
        self.store.complete(receipt.id)
        self.transaction.commit()
        structlog.get_logger().info(
            "worktree_operation_applied",
            operation_id=str(receipt.id),
            workspace_id=str(self.workspace_id),
            worktree_id=str(task.id),
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
            task = self.store.task(self.workspace_id, identifier)

            def prepare() -> tuple[str, str]:
                head = self.git.head(task.branch)
                if operation == "save":
                    return self.git.changed_tree(expected, changes or {}), head
                if operation == "discard":
                    return self.git.git("rev-parse", f"{head}^{{tree}}").decode().strip(), head
                if not message.strip():
                    raise RepositoryError("worktree_commit_message_required", 422)
                if self.files.clean(task.id, task.branch):
                    raise RepositoryError("worktree_nothing_to_commit")
                tree = self.git.git("rev-parse", f"{expected}^{{tree}}").decode().strip()
                return tree, self.git.commit_tree(tree, [head], message.strip(), str(self.user_id))

            return self.mutate_worktree(task, expected, key, payload, prepare)

    def create_worktree(
        self, identifier: UUID, title: str, branch: str, start: str
    ) -> WorkspaceTask:
        with self.open():
            self.ensure_native()
            self.authorize(True)
            branch_name(branch)
            digest = hashlib.sha256(json.dumps([title, branch, start]).encode()).hexdigest()
            key = f"create-worktree-{identifier}"
            receipt = self.store.receipt(self.workspace_id, self.user_id, key)
            if receipt and receipt.digest != digest:
                raise RepositoryError("worktree_retry_mismatch")
            existing = None
            for task in self.store.tasks(self.workspace_id, True):
                if task.id == identifier:
                    if (task.title, task.branch, task.created_by_user_id) != (
                        title,
                        branch,
                        self.user_id,
                    ):
                        raise RepositoryError("worktree_retry_mismatch")
                    existing = task
                elif task.branch == branch:
                    raise RepositoryError("worktree_branch_exists")
            if existing is None:
                if self.git.head(branch, missing=True):
                    raise RepositoryError("worktree_branch_exists")
                if self.store.task_identifier_taken(identifier):
                    raise RepositoryError("worktree_not_found", 404)
                head = self.git.head(start)
                now = utc_now()
                existing = WorkspaceTask(
                    identifier, self.workspace_id, title, branch, self.user_id, now, now, None
                )
                receipt = RepositoryReceipt(
                    uuid4(),
                    self.workspace_id,
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
                self.store.create_task(existing)
                self.transaction.commit()
            if existing.archived_at:
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

    def lifecycle(
        self,
        identifier: UUID,
        *,
        removed: bool,
        discard: bool = False,
        title: str | None = None,
        expected: str | None = None,
    ) -> WorkspaceTask:
        with self.open():
            self.ensure_native()
            task = self.store.task(self.workspace_id, identifier, lock=True)
            self.authorize(True)
            if self.store.branch_active(self.workspace_id, task.branch):
                raise RepositoryError("task_active")
            if removed:
                if (
                    expected
                    and task.archived_at is None
                    and self.files.revision(identifier) != expected
                ):
                    raise RepositoryError("worktree_stale_revision")
                if task.branch == "main":
                    raise RepositoryError("worktree_main_cannot_remove")
                if (
                    self.files.exists(identifier)
                    and not self.files.clean(identifier, task.branch)
                    and not discard
                ):
                    raise RepositoryError("worktree_discard_confirmation_required")
                # SQL tombstone first: a crash can leave a checkout, never expose it as active.
                updated = self.store.update_task(identifier, title, True)
                self.transaction.commit()
                self.files.remove(identifier, task.branch)
            else:
                if task.archived_at:
                    self.files.restore(identifier, task.branch)
                elif not self.files.available(identifier, task.branch):
                    self.files.apply(
                        identifier, task.branch, self.files.revision(identifier), create=True
                    )
                updated = self.store.update_task(identifier, title, False)
                self.transaction.commit()
            return updated
