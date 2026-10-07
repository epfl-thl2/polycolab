"""SQLite, fake S3 and local crypto evidence; no deployment acceptance."""

from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.engine import Connection
from test_artifacts import artifact_client as artifact_client
from test_artifacts import attach, upload
from test_catalogue_api import admit, enable, headers
from test_gateway import app_for, create_gateway_profile
from test_research_domain import create_object, create_workspace

from polycolab.db.models import (
    SqlContributionEnvelope,
    SqlGatewayProfile,
    SqlObjectRevision,
    SqlPublicationManifest,
    SqlPublicationRevision,
    SqlPublicRelease,
    SqlResearchObject,
    SqlRevisionEndorsement,
)
from polycolab.entities.enums import ContributionActorKind
from polycolab.entities.time import utc_now
from polycolab.model_gateway.credentials import (
    LocalAesGcmKeyWrapper,
    credential_context,
    encrypt_credential,
)
from polycolab.operations import recovery_dependencies
from polycolab.operations.recovery_dependencies import (
    verify_artifacts,
    verify_credentials,
    verify_research_integrity,
)
from polycolab.platform.outbox import canonical_digest


def test_restored_committed_artifacts_are_verified_outside_transaction(
    artifact_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = artifact_client
    project = create_workspace(client)
    target = create_object(client, project)
    uploaded = upload(client, project).json()
    assert (
        attach(client, project, uploaded["id"], target["current_object_version_id"]).status_code
        == 200
    )
    assert upload(client, project, b"uncommitted").status_code == 201
    app = app_for(client)
    active: set[int] = set()
    event.listen(app.state.engine, "begin", lambda connection: active.add(id(connection)))

    def ended(connection: Connection) -> None:
        active.discard(id(connection))

    event.listen(app.state.engine, "commit", ended)
    event.listen(app.state.engine, "rollback", ended)
    storage = app.state.artifact_storage
    get = storage.client.get_object

    def checked(**kwargs: Any) -> Any:
        assert not active
        return get(**kwargs)

    monkeypatch.setattr(storage.client, "get_object", checked)
    result = verify_artifacts(app.state.session_factory, storage, max_items=1)
    assert result.status == "VERIFIED" and result.checked == 1
    for key in storage.client.objects:
        storage.client.objects[key] = b"bad"
    assert verify_artifacts(app.state.session_factory, storage).status == "DEPENDENCY_FAILURE"
    storage.client.objects.clear()
    result = verify_artifacts(app.state.session_factory, storage)
    assert result.status == "DEPENDENCY_FAILURE" and result.checked == 0


def test_credentials_include_retained_deleted_profiles_and_fail_on_wrong_key(
    client: TestClient,
) -> None:
    create_gateway_profile(client)
    create_gateway_profile(client, "contributor")
    app = app_for(client)
    with app.state.session_factory() as session:
        profile = session.scalar(select(SqlGatewayProfile))
        assert profile is not None
        profile.deleted_at = utc_now()
        session.commit()
    report = verify_credentials(app.state.session_factory, app.state.credential_wrapper)
    assert report.status == "VERIFIED" and report.checked == 2
    report = verify_credentials(
        app.state.session_factory, app.state.credential_wrapper, max_items=1
    )
    assert report.status == "LIMIT_REACHED" and report.checked == 1
    report = verify_credentials(app.state.session_factory, LocalAesGcmKeyWrapper(b"x" * 32))
    assert report.status == "DEPENDENCY_FAILURE" and report.checked == 0


def test_key_io_occurs_after_transaction_close(client: TestClient) -> None:
    create_gateway_profile(client)
    app = app_for(client)
    active: set[int] = set()
    event.listen(app.state.engine, "begin", lambda connection: active.add(id(connection)))

    def ended(connection: Connection) -> None:
        active.discard(id(connection))

    event.listen(app.state.engine, "commit", ended)
    event.listen(app.state.engine, "rollback", ended)

    class Reader:
        key_version = app.state.credential_wrapper.key_version

        def unwrap(self, wrapped_key: bytes, context: bytes) -> bytes:
            assert not active
            return bytes(app.state.credential_wrapper.unwrap(wrapped_key, context))

        def wrap(self, plaintext_key: bytes, context: bytes) -> bytes:
            raise AssertionError("verification must not wrap credentials")

    assert verify_credentials(app.state.session_factory, Reader()).status == "VERIFIED"


def test_credential_scan_crosses_page_boundary(client: TestClient) -> None:
    create_gateway_profile(client)
    app = app_for(client)
    with app.state.session_factory() as session:
        source = session.scalar(select(SqlGatewayProfile))
        assert source is not None
        for _ in range(100):
            profile_id = uuid4()
            encrypted = encrypt_credential(
                app.state.credential_wrapper,
                context=credential_context(user_id=source.user_id, profile_id=profile_id),
                secret="synthetic-recovery-key",
            )
            session.add(
                SqlGatewayProfile(
                    id=profile_id,
                    user_id=source.user_id,
                    display_name="test",
                    base_url=source.base_url,
                    model_id=source.model_id,
                    encrypted_credential=encrypted.ciphertext,
                    wrapped_data_key=encrypted.wrapped_key,
                    encryption_key_version=encrypted.key_version,
                )
            )
        session.commit()
    report = verify_credentials(
        app.state.session_factory, app.state.credential_wrapper, max_items=101
    )
    assert report.status == "VERIFIED" and report.checked == 101
    report = verify_credentials(
        app.state.session_factory, app.state.credential_wrapper, max_items=100
    )
    assert report.status == "LIMIT_REACHED" and report.checked == 100


def test_cli_sanitizes_configuration_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failed() -> Any:
        raise RuntimeError("private-key-and-database-url")

    monkeypatch.setattr(recovery_dependencies, "get_settings", failed)
    assert recovery_dependencies.main(["credentials", "--isolated-restore"]) == 1
    assert capsys.readouterr().out == '{"status": "CONFIGURATION_OR_RUNTIME_FAILURE"}\n'


@pytest.mark.parametrize("max_items", [0, -1, 1_000_001, True])
def test_invalid_scan_bounds_are_rejected(client: TestClient, max_items: int) -> None:
    app = app_for(client)
    with pytest.raises(ValueError, match="invalid item bound"):
        verify_credentials(
            app.state.session_factory, app.state.credential_wrapper, max_items=max_items
        )


def test_database_failure_is_not_reported_as_verified(client: TestClient) -> None:
    app = app_for(client)

    def failed(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("private-database-details")

    event.listen(app.state.engine, "before_cursor_execute", failed)
    try:
        report = verify_credentials(app.state.session_factory, app.state.credential_wrapper)
        assert report.status == "DATABASE_FAILURE" and report.checked == 0
    finally:
        event.remove(app.state.engine, "before_cursor_execute", failed)


def test_restored_research_semantics_and_public_digest_are_verified(
    client: TestClient,
) -> None:
    project_id = create_workspace(client)
    created = create_object(client, project_id)
    app = app_for(client)
    revision_id = UUID(cast(str, created["current_object_version_id"]))
    with app.state.session_factory() as session:
        revision = session.get(SqlObjectRevision, revision_id)
        obj = session.get(SqlResearchObject, UUID(cast(str, created["id"])))
        assert revision is not None and obj is not None
        publication = SqlContributionEnvelope(
            actor_kind=ContributionActorKind.HUMAN,
            human_user_id=revision.created_by_user_id,
            ownership_scope_id=revision.ownership_scope_id,
            operation="publication.confirm",
            source_event_cursors=[],
        )
        session.add(publication)
        session.flush()
        manifest = SqlPublicationManifest(
            project_id=obj.project_id,
            ownership_scope_id=revision.ownership_scope_id,
            preview_digest="1" * 64,
            contribution_id=publication.id,
            created_by_user_id=revision.created_by_user_id,
            selection={},
            public_fields={},
        )
        session.add(manifest)
        session.flush()
        fields: dict[str, object] = {
            "object_id": str(obj.id),
            "revision_id": str(revision.id),
            "kind": "CLAIM",
            "title": "Claim",
            "content_md": "x",
            "assumptions_md": None,
            "author_display_name": "Owner",
        }
        release = SqlPublicRelease(
            ownership_scope_id=revision.ownership_scope_id,
            object_revision_id=revision.id,
            contribution_id=publication.id,
            publication_manifest_id=manifest.id,
            projection_version=3,
            public_fields=fields,
            public_fields_digest=canonical_digest(fields),
        )
        endorsement = SqlRevisionEndorsement(
            revision_id=revision.id,
            active=True,
            rationale="checked",
            contribution_id=revision.contribution_id,
            created_by_user_id=revision.created_by_user_id,
        )
        session.add_all(
            (
                SqlPublicationRevision(
                    manifest_id=manifest.id,
                    revision_id=revision.id,
                    position=0,
                    selected=True,
                ),
                release,
                endorsement,
            )
        )
        session.commit()
        release_id = release.id

    report = verify_research_integrity(app.state.session_factory)
    assert report.status == "VERIFIED" and report.checked == 6
    assert verify_research_integrity(app.state.session_factory, max_items=5).status == (
        "LIMIT_REACHED"
    )

    with app.state.session_factory() as session:
        release = session.get(SqlPublicRelease, release_id)
        assert release is not None
        release.public_fields_digest = "0" * 64
        session.commit()
    report = verify_research_integrity(app.state.session_factory)
    assert report.status == "INTEGRITY_FAILURE"
    assert report.sections == ("public_releases",)


def test_restored_revision_head_mismatch_is_reported_without_content(client: TestClient) -> None:
    project_id = create_workspace(client)
    created = create_object(client, project_id)
    app = app_for(client)
    with app.state.session_factory() as session:
        obj = session.get(SqlResearchObject, UUID(cast(str, created["id"])))
        assert obj is not None
        obj.current_revision_id = None
        session.commit()
    report = verify_research_integrity(app.state.session_factory)
    assert report.status == "INTEGRITY_FAILURE"
    assert report.sections == ("revision_heads",)


def test_restore_verifier_accepts_independently_scoped_equivalence(client: TestClient) -> None:
    app = enable(client)
    first, second = admit(client, "first"), admit(client, "second")
    project = create_workspace(client)
    response = client.post(
        "/api/v1/relations",
        headers=headers(),
        json={
            "direction": "BIDIRECTIONAL",
            "relationship_type": "EQUIVALENT_TO",
            "destination": {"kind": "workspace", "workspace_id": project},
            "first_object_version_id": first["object_version_id"],
            "second_object_version_id": second["object_version_id"],
        },
    )
    assert response.status_code == 201, response.text
    assert verify_research_integrity(app.state.session_factory).status == "VERIFIED"


def test_restore_verifier_counts_and_checks_structural_relationships(client: TestClient) -> None:
    from polycolab.db.models.relationships import SqlObjectVersionRelationship

    project = create_workspace(client)
    proof = create_object(client, project, kind="PROOF_SKETCH")
    unrelated = create_object(client, project)
    app = app_for(client)
    before = verify_research_integrity(app.state.session_factory)
    assert before.status == "VERIFIED"
    # Three identities, three versions and two structural relationships.
    assert before.checked == 8
    assert (
        verify_research_integrity(app.state.session_factory, max_items=7).status == "LIMIT_REACHED"
    )
    with app.state.session_factory() as session:
        pin = session.scalar(
            select(SqlObjectVersionRelationship).where(
                SqlObjectVersionRelationship.source_object_version_id
                == UUID(proof["current_object_version_id"])
            )
        )
        other = session.get(SqlObjectRevision, UUID(unrelated["current_object_version_id"]))
        assert pin is not None and other is not None
        # Simulate restored corruption not prevented by SQLite's reduced constraints.
        pin.contribution_id = other.contribution_id
        session.commit()
    report = verify_research_integrity(app.state.session_factory)
    assert report.status == "INTEGRITY_FAILURE"
    assert report.sections == ("relations",)


@pytest.mark.parametrize("missing_role", ["CONCLUSION", "ATTACHMENT", "TARGET"])
def test_restore_verifier_rejects_incomplete_structure(
    client: TestClient, missing_role: str
) -> None:
    from polycolab.db.models.relationships import SqlObjectVersionRelationship

    project = create_workspace(client)
    created = create_object(
        client, project, kind="ATTEMPT" if missing_role == "TARGET" else "PROOF_SKETCH"
    )
    app = app_for(client)
    assert verify_research_integrity(app.state.session_factory).status == "VERIFIED"
    with app.state.session_factory() as session:
        pin = session.scalar(
            select(SqlObjectVersionRelationship).where(
                SqlObjectVersionRelationship.source_object_version_id
                == UUID(created["current_object_version_id"]),
                SqlObjectVersionRelationship.relationship_type == missing_role,
            )
        )
        assert pin is not None
        # SQLite permits simulating a damaged restore without disabling production triggers.
        session.delete(pin)
        session.commit()
    report = verify_research_integrity(app.state.session_factory)
    assert report.status == "INTEGRITY_FAILURE"
    assert report.sections == ("relations",)


@pytest.mark.parametrize("kind", ["PROOF_SKETCH", "ATTEMPT"])
def test_restore_verifier_rejects_incompatible_structural_target(
    client: TestClient, kind: str
) -> None:
    from polycolab.db.models.relationships import SqlObjectVersionRelationship

    project = create_workspace(client)
    created = create_object(client, project, kind=kind)
    incompatible = create_object(client, project, kind="ATTEMPT")
    app = app_for(client)
    assert verify_research_integrity(app.state.session_factory).status == "VERIFIED"
    with app.state.session_factory() as session:
        for pin in session.scalars(
            select(SqlObjectVersionRelationship).where(
                SqlObjectVersionRelationship.source_object_version_id
                == UUID(created["current_object_version_id"])
            )
        ):
            pin.target_object_version_id = UUID(incompatible["current_object_version_id"])
        session.commit()
    report = verify_research_integrity(app.state.session_factory)
    assert report.status == "INTEGRITY_FAILURE"
    assert report.sections == ("relations",)


@pytest.mark.parametrize("different_object", [False, True])
def test_restore_verifier_rejects_invalid_attempt_result(
    client: TestClient, different_object: bool
) -> None:
    from polycolab.db.models.relationships import SqlObjectVersionRelationship

    project = create_workspace(client)
    created = create_object(client, project, kind="ATTEMPT")
    unrelated = create_object(client, project)
    app = app_for(client)
    assert verify_research_integrity(app.state.session_factory).status == "VERIFIED"
    with app.state.session_factory() as session:
        target = session.scalar(
            select(SqlObjectVersionRelationship).where(
                SqlObjectVersionRelationship.source_object_version_id
                == UUID(created["current_object_version_id"]),
                SqlObjectVersionRelationship.relationship_type == "TARGET",
            )
        )
        assert target is not None
        session.add(
            SqlObjectVersionRelationship(
                relationship_type="RESULT",
                binding="STRUCTURAL",
                direction="UNIDIRECTIONAL",
                source_object_version_id=target.source_object_version_id,
                target_object_version_id=(
                    UUID(unrelated["current_object_version_id"])
                    if different_object
                    else target.target_object_version_id
                ),
                ownership_scope_id=target.ownership_scope_id,
                contribution_id=target.contribution_id,
                created_by_user_id=target.created_by_user_id,
                provenance_kind=target.provenance_kind,
                created_at=target.created_at,
            )
        )
        session.commit()
    report = verify_research_integrity(app.state.session_factory)
    assert report.status == "INTEGRITY_FAILURE"
    assert report.sections == ("relations",)
