"""Authorization and durable lifecycle for immutable worktree compilations."""

import hashlib
from dataclasses import dataclass, replace
from datetime import timedelta
from io import BytesIO
from uuid import UUID, uuid4

from polycolab.access.authorization import ProjectAction, project_policy
from polycolab.artifacts.storage import ArtifactStorage, new_staging_key
from polycolab.document_builds.store import BuildStore
from polycolab.entities.artifacts import ArtifactIntegrity, ArtifactStorageError
from polycolab.entities.document_builds import (
    ACTIVE,
    BuildBlob,
    BuildError,
    BuildLimits,
    BuildStatus,
    DocumentBuild,
    Engine,
)
from polycolab.entities.time import utc_now
from polycolab.transaction import Transaction


@dataclass
class BuildService:
    transaction: Transaction
    store: BuildStore
    storage: ArtifactStorage
    image: str | None
    limits: BuildLimits

    def authorize(self, project: UUID, user: UUID, write: bool = False) -> None:
        project_policy.require_scope(
            self.transaction,
            project,
            user,
            ProjectAction.CREATE_RESEARCH if write else ProjectAction.VIEW,
        )

    def available(self) -> bool:
        until, image = self.store.lock_queue()
        self.transaction.commit()
        return bool(self.image and image == self.image and until and until > utc_now())

    def ready(self, image: str) -> None:
        if not self.image or image != self.image:
            raise BuildError("latex_image_mismatch", 503)
        self.store.lock_queue()
        self.store.ready(image, utc_now() + timedelta(seconds=45))
        self.transaction.commit()

    def get(self, project: UUID, worktree: UUID, identifier: UUID, user: UUID) -> DocumentBuild:
        self.authorize(project, user)
        build = self.store.get(identifier)
        if not build or build.project_id != project or build.worktree_id != worktree:
            raise BuildError("latex_build_not_found", 404)
        if build.expires_at <= utc_now():
            raise BuildError("latex_build_expired", 410)
        return build

    def retry(
        self,
        project: UUID,
        worktree: UUID,
        user: UUID,
        key: str,
        revision: str,
        main_file: str,
        engine: Engine,
    ) -> DocumentBuild | None:
        build = self.store.retry(project, worktree, user, key)
        if build and (build.revision, build.main_file, build.engine) != (
            revision,
            main_file,
            engine,
        ):
            raise BuildError("latex_retry_mismatch")
        return build

    def submit(
        self,
        project: UUID,
        worktree: UUID,
        user: UUID,
        key: str,
        revision: str,
        main_file: str,
        engine: Engine,
        data: bytes,
    ) -> DocumentBuild:
        now = utc_now()
        until, image = self.store.lock_queue()
        self.authorize(project, user, True)
        previous = self.retry(project, worktree, user, key, revision, main_file, engine)
        if previous:
            return previous
        if not self.image or image != self.image or not until or until <= now:
            raise BuildError("latex_worker_unavailable", 503)
        pending = self.store.pending(project)
        if any(item.worktree_id == worktree for item in pending) or any(
            item.worktree_id == worktree for item in self.store.occupied(now)
        ):
            raise BuildError("latex_worktree_busy")
        if sum(item.project_id == project for item in pending) >= self.limits.project_queue:
            raise BuildError("latex_queue_full", 429)
        if self.store.project_usage(project) + len(data) > self.limits.project_bytes:
            raise BuildError("latex_storage_full", 413)
        integrity = ArtifactIntegrity(hashlib.sha256(data).hexdigest(), len(data))
        source = BuildBlob(new_staging_key(), integrity.sha256, integrity.byte_length, True)
        build = DocumentBuild(
            uuid4(),
            project,
            worktree,
            user,
            key,
            revision,
            main_file,
            engine,
            self.image,
            "preparing",
            now,
            now + timedelta(days=self.limits.retention_days),
            source,
            {},
        )
        self.store.create(build)
        self.transaction.commit()
        try:
            self.storage.put_verified(source.key, BytesIO(data), integrity)
        except ArtifactStorageError:
            self.store.lock_queue()
            self.store.state(build.id, "failed", "latex_input_upload_failed")
            self.transaction.commit()
            raise
        self.store.lock_queue()
        current = self.store.get(build.id)
        assert current is not None
        if current.status == "preparing":
            self.authorize(project, user, True)
            self.store.state(build.id, "queued")
        self.transaction.commit()
        result = self.store.get(build.id)
        assert result is not None
        return result

    def recover(self) -> None:
        self.store.lock_queue()
        now = utc_now()
        for build in self.store.pending():
            if build.status == "running":
                if build.deadline and build.deadline <= now:
                    self.store.state(build.id, "timed_out", "latex_timeout")
                elif build.lease_until and build.lease_until <= now:
                    self.store.state(build.id, "failed", "latex_worker_lost")
            elif (now - build.created_at).total_seconds() > self.limits.queue_seconds:
                self.store.state(build.id, "timed_out", "latex_queue_timeout")
        self.transaction.commit()

    def eligible(self, build: DocumentBuild) -> bool:
        return project_policy.can(
            self.transaction, build.project_id, build.requested_by, ProjectAction.CREATE_RESEARCH
        ) and self.store.worktree_available(build.project_id, build.worktree_id)

    def claim(self, worker: str) -> DocumentBuild | None:
        self.recover()
        self.store.lock_queue()
        now = utc_now()
        occupied = self.store.occupied(now)
        if len(occupied) >= self.limits.capacity:
            self.transaction.commit()
            return None
        for build in self.store.pending():
            if build.status != "queued" or any(
                item.worktree_id == build.worktree_id for item in occupied
            ):
                continue
            if not self.eligible(build):
                self.store.state(build.id, "cancelled", "latex_access_revoked")
                continue
            if build.image != self.image:
                self.store.state(build.id, "failed", "latex_image_changed")
                continue
            self.authorize(build.project_id, build.requested_by, True)
            deadline = now + timedelta(seconds=self.limits.execution_seconds)
            self.store.claim(
                build.id,
                worker,
                uuid4(),
                now + timedelta(seconds=30),
                deadline,
                deadline + timedelta(seconds=30),
            )
            self.transaction.commit()
            return self.store.get(build.id)
        self.transaction.commit()
        return None

    def attempt(self, identifier: UUID, generation: UUID) -> DocumentBuild:
        build = self.store.get(identifier)
        now = utc_now()
        if (
            not build
            or build.generation != generation
            or build.status != "running"
            or not build.lease_until
            or build.lease_until <= now
            or not build.deadline
            or build.deadline <= now
        ):
            raise BuildError("latex_attempt_expired")
        if not self.eligible(build):
            self.store.state(identifier, "cancelled", "latex_access_revoked")
            self.transaction.commit()
            raise BuildError("latex_attempt_expired")
        return build

    def heartbeat(self, identifier: UUID, generation: UUID) -> None:
        self.store.lock_queue()
        build = self.attempt(identifier, generation)
        assert build.deadline
        self.store.ready(build.image, utc_now() + timedelta(seconds=45))
        self.store.heartbeat(identifier, min(build.deadline, utc_now() + timedelta(seconds=30)))
        self.transaction.commit()

    def input_bytes(self, identifier: UUID, generation: UUID) -> bytes:
        self.store.lock_queue()
        build = self.attempt(identifier, generation)
        self.transaction.commit()
        data = self.read_blob(build.input)
        self.store.lock_queue()
        self.attempt(identifier, generation)
        self.transaction.commit()
        return data

    def read_blob(self, blob: BuildBlob) -> bytes:
        if not blob.key or not blob.verified:
            raise BuildError("latex_output_unavailable", 404)
        return self.storage.get_verified(blob.key, ArtifactIntegrity(blob.sha256, blob.byte_length))

    def upload(self, identifier: UUID, generation: UUID, kind: str, data: bytes) -> None:
        if kind not in {"pdf", "log"} or len(data) > (
            1024 * 1024 if kind == "log" else 16 * 1024 * 1024
        ):
            raise BuildError("latex_output_limit", 413)
        if kind == "pdf" and not data.startswith(b"%PDF-"):
            raise BuildError("latex_invalid_pdf", 422)
        integrity = ArtifactIntegrity(hashlib.sha256(data).hexdigest(), len(data))
        self.store.lock_queue()
        build = self.attempt(identifier, generation)
        previous = build.outputs.get(kind)
        if previous and (previous.sha256, previous.byte_length) != (integrity.sha256, len(data)):
            raise BuildError("latex_output_mismatch")
        if previous and previous.verified:
            self.transaction.commit()
            return
        if (
            not previous
            and self.store.project_usage(build.project_id) + len(data) > self.limits.project_bytes
        ):
            raise BuildError("latex_storage_full", 413)
        output = previous or BuildBlob(new_staging_key(), integrity.sha256, len(data))
        self.store.output(identifier, kind, output)
        self.transaction.commit()
        # An ambiguous previous PUT may already have published the exact blob.
        try:
            self.storage.get_verified(output.key, integrity)
        except ArtifactStorageError:
            self.storage.put_verified(output.key, BytesIO(data), integrity)
        self.store.lock_queue()
        self.attempt(identifier, generation)
        self.store.output(identifier, kind, replace(output, verified=True))
        self.transaction.commit()

    def finish(
        self, identifier: UUID, generation: UUID, status: BuildStatus, error: str | None
    ) -> None:
        self.store.lock_queue()
        build = self.store.get(identifier)
        if (
            build
            and build.generation == generation
            and build.status == status
            and build.error == error
        ):
            self.transaction.commit()
            return
        build = self.attempt(identifier, generation)
        self.authorize(build.project_id, build.requested_by, True)
        if status == "succeeded" and not (
            build.outputs.get("pdf") and build.outputs["pdf"].verified
        ):
            raise BuildError("latex_pdf_required")
        self.store.state(identifier, status, error)
        self.transaction.commit()

    def release(self, identifier: UUID, generation: UUID) -> None:
        self.store.lock_queue()
        build = self.store.get(identifier)
        if not build or build.generation != generation:
            raise BuildError("latex_attempt_expired")
        if build.status in ACTIVE:
            self.store.state(identifier, "failed", "latex_worker_stopped")
        self.store.release(identifier)
        self.transaction.commit()

    def cancel(self, project: UUID, worktree: UUID, identifier: UUID, user: UUID) -> DocumentBuild:
        self.store.lock_queue()
        self.authorize(project, user, True)
        build = self.get(project, worktree, identifier, user)
        if build.status in ACTIVE:
            self.store.state(identifier, "cancelled")
        self.transaction.commit()
        return self.get(project, worktree, identifier, user)

    def cleanup(self) -> None:
        self.recover()
        now = utc_now()
        candidates = self.store.cleanup_candidates(now)
        self.transaction.commit()
        for build in candidates:
            # Uploads have finite HTTP deadlines; allow an additional grace period
            # before forgetting a key so late PUTs cannot escape cleanup.
            if (now - (build.deadline or build.created_at)).total_seconds() < 600:
                continue
            blobs = {"input": build.input}
            if build.expires_at <= now:
                blobs.update(build.outputs)
            for kind, item in blobs.items():
                if item.key:
                    self.storage.delete(item.key)
                    self.store.forget_blob(build.id, kind)
                    self.transaction.commit()
