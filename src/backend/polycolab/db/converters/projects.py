"""Materialized project state and member-facing multi-table projections."""

from polycolab.db.converters.time import timestamp
from polycolab.db.models.projects import SqlInvitation, SqlMembership, SqlProject
from polycolab.entities.projects import Invitation, Membership, Project


def project(row: SqlProject) -> Project:
    return Project(
        id=row.id,
        name=row.name,
        description=row.description,
        visibility=row.visibility,
        created_by_user_id=row.created_by_user_id,
        created_at=timestamp(row.created_at),
        updated_at=timestamp(row.updated_at),
        archived_at=timestamp(row.archived_at),
        deleted_at=timestamp(row.deleted_at),
    )


def membership(row: SqlMembership) -> Membership:
    return Membership(
        id=row.id,
        project_id=row.project_id,
        user_id=row.user_id,
        role=row.role,
        invited_by_user_id=row.invited_by_user_id,
        created_at=timestamp(row.created_at),
        updated_at=timestamp(row.updated_at),
    )


def invitation(row: SqlInvitation) -> Invitation:
    return Invitation(
        id=row.id,
        project_id=row.project_id,
        email=row.email,
        role=row.role,
        invited_by_user_id=row.invited_by_user_id,
        expires_at=timestamp(row.expires_at),
        status=row.status,
        accepted_by_user_id=row.accepted_by_user_id,
        accepted_at=timestamp(row.accepted_at),
        revoked_at=timestamp(row.revoked_at),
        created_at=timestamp(row.created_at),
    )
