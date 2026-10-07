"""Stored activity identities survive persistence-class renames."""

from typing import Any
from unittest.mock import Mock
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy.orm import Session

from polycolab.db.models import (
    SqlArtifactResearchLink,
    SqlCatalogueAudit,
    SqlObjectRevision,
    SqlPublicRelease,
    SqlRelationAssertion,
    SqlResearchComment,
    SqlResearchProgressUpdate,
    SqlResearchSummaryRevision,
)
from polycolab.db.models.relationships import SqlObjectVersionRelationship
from polycolab.entities.time import utc_now
from polycolab.research.history import from_source


@pytest.mark.parametrize(
    ("model", "legacy_kind"),
    [
        (SqlObjectRevision, "ObjectRevision"),
        (SqlResearchComment, "ResearchComment"),
        (SqlRelationAssertion, "RelationAssertion"),
        (SqlArtifactResearchLink, "ArtifactResearchLink"),
        (SqlResearchProgressUpdate, "ResearchProgressUpdate"),
        (SqlResearchSummaryRevision, "ResearchSummaryRevision"),
        (SqlPublicRelease, "PublicRelease"),
        (SqlCatalogueAudit, "CatalogueAudit"),
    ],
)
def test_activity_uses_legacy_source_kind_and_uuid(model: type[Any], legacy_kind: str) -> None:
    at = utc_now()
    revision = SqlObjectRevision(
        id=uuid4(),
        object_id=uuid4(),
        ownership_scope_id=uuid4(),
        number=1,
        created_at=at,
        contribution_id=None,
    )
    source = model(id=uuid4(), contribution_id=None, created_at=at)
    if isinstance(source, SqlObjectRevision):
        source = revision
    elif isinstance(source, SqlRelationAssertion):
        source.source_revision_id = revision.id
        source.ownership_scope_id = revision.ownership_scope_id
    elif isinstance(source, SqlResearchSummaryRevision):
        source.object_id = revision.object_id
        source.number = 1
    elif isinstance(source, SqlPublicRelease):
        source.object_revision_id = revision.id
        source.publication_manifest_id = uuid4()
    else:
        source.revision_id = revision.id
        if isinstance(source, SqlCatalogueAudit):
            source.action = "PROMOTE"
    session = Mock(spec=Session)
    session.get.return_value = revision
    session.scalar.return_value = revision
    event = from_source(session, source)
    assert event is not None
    assert event.source_kind == legacy_kind
    assert event.source_id == source.id
    assert event.id == uuid5(NAMESPACE_URL, f"polycolab:activity:{legacy_kind}:{source.id}")


def test_canonical_declaration_keeps_relation_assertion_identity() -> None:
    revision = SqlObjectRevision(id=uuid4(), object_id=uuid4(), ownership_scope_id=uuid4())
    declaration = SqlRelationAssertion(
        id=uuid4(),
        source_revision_id=revision.id,
        ownership_scope_id=revision.ownership_scope_id,
        contribution_id=None,
        created_at=utc_now(),
    )
    relationship = SqlObjectVersionRelationship(id=declaration.id, binding="DECLARATION")
    session = Mock(spec=Session)
    session.get.side_effect = [declaration, revision]
    event = from_source(session, relationship)
    assert event is not None
    assert event.source_kind == "RelationAssertion"
    assert event.id == uuid5(
        NAMESPACE_URL, f"polycolab:activity:RelationAssertion:{declaration.id}"
    )
    session.get.assert_any_call(SqlRelationAssertion, declaration.id)
    relationship.binding = "STRUCTURAL"
    assert from_source(session, relationship) is None
