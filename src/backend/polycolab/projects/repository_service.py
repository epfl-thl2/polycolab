"""Project working-file policy and recoverable Git/SQL coordination."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from polycolab.projects.worktree_service import WorktreeService

from polycolab.access.authorization import ProjectAction, project_policy
from polycolab.entities.repositories import ProjectTask, RepositoryError, RepositoryReceipt
from polycolab.entities.time import utc_now
from polycolab.projects.git_storage import GitRepository
from polycolab.projects.repository_store import RepositoryStore
from polycolab.transaction import Transaction


def decode_changes(changes: list[tuple[str, str | None]]) -> dict[str, bytes | None]:
    result: dict[str, bytes | None] = {}
    for path, content in changes:
        if path in result:
            raise RepositoryError("repository_duplicate_path", 422)
        try:
            result[path] = base64.b64decode(content, validate=True) if content is not None else None
        except ValueError:
            raise RepositoryError("repository_invalid_content", 422) from None
    return result


@dataclass
class RepositoryService:
    transaction: Transaction
    store: RepositoryStore
    git: GitRepository
    project_id: UUID
    user_id: UUID

    def authorize(self, write: bool = False, branch: str = "main") -> None:
        project_policy.require_scope(
            self.transaction,
            self.project_id,
            self.user_id,
            ProjectAction.CREATE_RESEARCH if write else ProjectAction.VIEW,
        )
        if write:
            self.store.lock_branch(self.project_id, branch)
        if write and self.store.branch_active(self.project_id, branch):
            raise RepositoryError("task_active")
        if write and self.store.branch_archived(self.project_id, branch):
            raise RepositoryError("task_archived")

    @contextmanager
    def open(self) -> Iterator[GitRepository]:
        self.authorize()
        registered = self.store.registered(self.project_id)
        self.transaction.commit()
        with self.git.locked(initialize=not registered):
            self.store.register(self.project_id)
            from polycolab.projects.worktree_storage import WorktreeStorage

            files = WorktreeStorage(self.git)
            files.recover()
            tasks = {task.branch: task for task in self.store.tasks(self.project_id, True)}
            for receipt in self.store.pending(self.project_id):
                task = tasks.get(receipt.branch)
                if task and files.exists(task.id) and files.contains(task.id, receipt.new_commit):
                    self.store.complete(receipt.id)
                    continue
                if self.git.contains(receipt.branch, receipt.new_commit):
                    self.store.complete(receipt.id)
            self.transaction.commit()
            yield self.git

    def mutate(
        self,
        *,
        branch: str,
        expected: str,
        key: str,
        payload: object,
        prepare: Callable[[], str],
        authority: Callable[[], None] | None = None,
    ) -> str:
        """Caller holds repository lock. SQL receipt precedes the ref update.

        Final authority locks fence membership/archive changes during the short
        ref update. Recovery only acknowledges an already-applied operation;
        it never applies a write on behalf of a revoked user.
        """
        (authority or (lambda: self.authorize(True, branch)))()
        self.transaction.commit()
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        receipt = self.store.receipt(self.project_id, self.user_id, key)
        self.transaction.commit()
        if receipt is not None:
            if receipt.digest != digest or receipt.branch != branch:
                raise RepositoryError("repository_retry_mismatch")
            if receipt.completed:
                return receipt.new_commit
        else:
            if self.git.head(branch) != expected:
                raise RepositoryError("repository_stale_save")
            new_commit = prepare()
            if self.git.size() > self.git.quota:
                raise RepositoryError("repository_quota_exceeded", 413)
            receipt = RepositoryReceipt(
                uuid4(),
                self.project_id,
                self.user_id,
                key,
                digest,
                branch,
                expected,
                new_commit,
                False,
                utc_now(),
            )
            self.store.prepare(receipt)
            self.transaction.commit()
        (authority or (lambda: self.authorize(True, branch)))()
        if not self.git.contains(branch, receipt.new_commit):
            if self.git.head(branch) != receipt.old_commit:
                raise RepositoryError("repository_stale_save")
            self.git.advance(branch, receipt.old_commit, receipt.new_commit)
        self.store.complete(receipt.id)
        self.transaction.commit()
        return receipt.new_commit

    def save(
        self,
        *,
        branch: str,
        expected: str,
        key: str,
        changes: dict[str, bytes | None],
        payload: object,
    ) -> str:
        with self.open():
            if self.store.native(self.project_id):
                raise RepositoryError("repository_upgrade_required_use_worktrees")
            return self.mutate(
                branch=branch,
                expected=expected,
                key=key,
                payload=payload,
                prepare=lambda: self.git.commit_tree(
                    self.git.changed_tree(expected, changes),
                    [expected],
                    "Save project files",
                    str(self.user_id),
                ),
            )

    def preview(self, target: str, source: str) -> dict[str, object]:
        with self.open():
            if self.store.native(self.project_id):
                self.require_clean_branches(target, source)
            current, incoming = self.git.head(target), self.git.head(source)
            _, paths = self.git.merge(current, incoming)
            base = self.git.git("merge-base", current, incoming).decode().strip()
            entries = {c: self.git.entries(c) for c in (base, current, incoming)}

            def content(commit: str, path: str) -> str | None:
                return (
                    base64.b64encode(self.git.read(commit, path)).decode()
                    if path in entries[commit]
                    else None
                )

            revisions = {}
            if self.store.native(self.project_id):
                native = self.native_service()
                revisions = {
                    "target_revision": native.files.revision(native.task_for_branch(target).id),
                    "source_revision": native.files.revision(native.task_for_branch(source).id),
                }
            return {
                **revisions,
                "target_commit": current,
                "source_commit": incoming,
                "diff": self.git.diff(current, incoming),
                "conflicts": [
                    {
                        "path": path,
                        "base_base64": content(base, path),
                        "current_base64": content(current, path),
                        "incoming_base64": content(incoming, path),
                    }
                    for path in paths
                ],
            }

    def merge(
        self,
        *,
        target: str,
        source: str,
        expected_target: str,
        expected_source: str,
        resolutions: dict[str, bytes | None] | None,
        key: str,
        payload: object,
        expected_target_revision: str | None = None,
        expected_source_revision: str | None = None,
    ) -> str:
        with self.open():

            def prepare() -> str:
                if source == target or self.git.head(source) != expected_source:
                    raise RepositoryError("repository_stale_merge")
                tree, conflicts = self.git.merge(expected_target, expected_source)
                if conflicts:
                    if resolutions is None or set(resolutions) != set(conflicts):
                        raise RepositoryError("repository_merge_conflicts")
                    # merge-tree's tree includes automatic resolutions for unrelated paths.
                    temporary = self.git.commit_tree(
                        tree, [expected_target], "Merge preparation", "Polycolab"
                    )
                    existing = self.git.entries(temporary)
                    actual = {
                        p: c for p, c in resolutions.items() if c is not None or p in existing
                    }
                    tree = self.git.changed_tree(temporary, actual)
                elif resolutions:
                    raise RepositoryError("repository_unexpected_resolutions", 422)
                return self.git.commit_tree(
                    tree,
                    [expected_target, expected_source],
                    "Merge project changes",
                    str(self.user_id),
                )

            if self.store.native(self.project_id):
                native = self.native_service()
                task = native.task_for_branch(target)
                if not expected_target_revision or not expected_source_revision:
                    raise RepositoryError("worktree_revision_required")

                def prepare_native() -> tuple[str, str]:
                    self.require_clean_branches(target, source)
                    if (
                        native.files.revision(native.task_for_branch(source).id)
                        != expected_source_revision
                    ):
                        raise RepositoryError("worktree_stale_revision")
                    if self.git.head(target) != expected_target:
                        raise RepositoryError("repository_stale_merge")
                    commit = prepare()
                    return self.git.git("rev-parse", f"{commit}^{{tree}}").decode().strip(), commit

                revision = native.mutate_worktree(
                    task, expected_target_revision, key, payload, prepare_native
                )
                return native.files.snapshot_head(revision)

            return self.mutate(
                branch=target, expected=expected_target, key=key, payload=payload, prepare=prepare
            )

    def enable_session(self, session_id: UUID) -> str:
        with self.open():
            self.authorize(True)
            session = self.store.session(self.project_id, session_id)
            if session.owner_id != self.user_id:
                raise RepositoryError("repository_session_not_found", 404)
            branch = session.branch or f"sessions/{session_id}"
            if session.enabled:
                self.transaction.commit()
                return branch
            if session.active:
                raise RepositoryError("repository_session_active")
            self.transaction.commit()
            commit = self.git.head("main")
            if not self.git.head(branch, missing=True):
                self.git.advance(branch, "0" * 40, commit)
            self.authorize(True)
            if self.store.session_active(self.project_id, session_id):
                raise RepositoryError("repository_session_active")
            self.store.enable_session(self.project_id, session_id, commit)
            self.transaction.commit()
            return branch

    def pin_run(self, run_id: UUID, session_id: UUID) -> dict[str, str] | None:
        session = self.store.session(self.project_id, session_id)
        self.transaction.commit()
        if not session.enabled:
            return None
        if self.store.public_run(run_id):
            raise RepositoryError("repository_public_run_denied", 403)
        self.transaction.commit()
        with self.open():
            binding = self.store.run(run_id)
            branch = session.branch or f"sessions/{session_id}"
            if binding is None:
                self.store.enable_session(self.project_id, session_id, self.git.head(branch))
                revision = None
                worktree_id = None
                if self.store.native(self.project_id):
                    native = self.native_service()
                    task = native.task_for_branch(branch)
                    revision = native.require_available(task)
                    worktree_id = task.id
                self.store.pin_run(
                    run_id, session_id, self.git.head(branch), branch, revision, worktree_id
                )
                self.transaction.commit()
                binding = self.store.run(run_id)
            assert binding is not None
            result = {"branch": branch, "commit": binding.input_commit}
            if binding.input_revision:
                result["revision"] = binding.input_revision
            if binding.worktree_id:
                result["worktree_id"] = str(binding.worktree_id)
            return result

    def export_run(self, run_id: UUID, data: bytes, authority: Callable[[], None]) -> str:
        with self.open():
            binding = self.store.run(run_id)
            if binding is None:
                raise RepositoryError("repository_not_in_run", 403)
            self.transaction.commit()
            branch = binding.branch or f"sessions/{binding.session_id}"
            if binding.input_revision and binding.worktree_id:
                native = self.native_service()
                task = self.store.task(self.project_id, binding.worktree_id)

                def prepare_native() -> tuple[str, str]:
                    imported = self.git.import_bundle(data, branch, binding.input_commit)
                    tree = self.git.git("rev-parse", f"{imported}^{{tree}}").decode().strip()
                    return tree, binding.input_commit

                revision = native.mutate_worktree(
                    task,
                    binding.input_revision,
                    f"run-{run_id}",
                    {"sha256": hashlib.sha256(data).hexdigest()},
                    prepare_native,
                    authority,
                )
                self.store.finish_run(run_id, revision)
                self.transaction.commit()
                return revision
            commit = self.mutate(
                branch=branch,
                expected=binding.input_commit,
                key=f"run-{run_id}",
                payload={"sha256": hashlib.sha256(data).hexdigest()},
                prepare=lambda: self.git.import_bundle(data, branch, binding.input_commit),
                authority=authority,
            )
            self.store.finish_run(run_id, commit)
            self.transaction.commit()
            return commit

    def create_task(self, task_id: UUID, title: str) -> ProjectTask:
        if self.store.native(self.project_id):
            return self.native_service().create_worktree(task_id, title, f"tasks/{task_id}", "main")
        with self.open():
            self.authorize(True)
            try:
                existing = self.store.task(self.project_id, task_id)
            except RepositoryError as error:
                if error.status != 404:
                    raise
            else:
                if existing.created_by_user_id != self.user_id:
                    raise RepositoryError("project_task_not_found", 404)
                if existing.title != title:
                    raise RepositoryError("task_retry_conflict")
                self.transaction.commit()
                return existing
            if self.store.task_identifier_taken(task_id):
                raise RepositoryError("project_task_not_found", 404)
            branch = f"tasks/{task_id}"
            head = self.git.head("main")
            if not self.git.head(branch, missing=True):
                self.git.advance(branch, "0" * 40, head)
            now = utc_now()
            task = ProjectTask(
                task_id, self.project_id, title, branch, self.user_id, now, now, None
            )
            self.store.create_task(task)
            self.transaction.commit()
            return task

    def update_task(self, task_id: UUID, title: str | None, archived: bool | None) -> ProjectTask:
        if self.store.native(self.project_id):
            task = self.store.task(self.project_id, task_id)
            return self.native_service().lifecycle(
                task_id,
                removed=archived if archived is not None else task.archived_at is not None,
                title=title,
            )
        with self.open():
            self.authorize(True)
            task = self.store.task(self.project_id, task_id, lock=True)
            if archived is True and self.store.branch_active(self.project_id, task.branch):
                raise RepositoryError("task_active")
            updated = self.store.update_task(task_id, title, archived)
            self.transaction.commit()
            return updated

    def native_service(self) -> WorktreeService:
        from polycolab.projects.worktree_service import WorktreeService

        return WorktreeService(
            self.transaction, self.store, self.git, self.project_id, self.user_id
        )

    def require_clean_branches(self, *branches: str) -> None:
        native = self.native_service()
        for branch in branches:
            task = native.task_for_branch(branch)
            native.require_available(task)
            if not native.files.clean(task.id, branch):
                raise RepositoryError("worktree_merge_requires_clean_files")
            if self.store.branch_active(self.project_id, branch):
                raise RepositoryError("task_active")
