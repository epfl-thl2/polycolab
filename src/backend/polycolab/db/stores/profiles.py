"""Bounded public profile reads, sharing the research history visibility policy."""

from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from polycolab.app.access import ResearchAccess
from polycolab.db.errors import persistence_boundary
from polycolab.db.models import SqlUser
from polycolab.entities.profiles import PublicResearcher
from polycolab.research.history import visible_query


class SqlProfileReadStore:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _query(self) -> Select[Any]:
        public = visible_query(ResearchAccess(), "public").subquery()
        contribution = func.coalesce(public.c.contribution_id, public.c.id)
        authored = (
            select(
                public.c.actor_user_id.label("user_id"),
                func.count(func.distinct(contribution)).label("count"),
            )
            .group_by(public.c.actor_user_id)
            .subquery()
        )
        sponsored = (
            select(
                public.c.sponsor_user_id.label("user_id"),
                func.count(func.distinct(contribution)).label("count"),
            )
            .group_by(public.c.sponsor_user_id)
            .subquery()
        )
        name = func.coalesce(func.nullif(SqlUser.display_name, ""), "Researcher")
        return (
            select(
                SqlUser.id.label("user_id"),
                SqlUser.username,
                name.label("display_name"),
                func.coalesce(authored.c.count, 0).label("authored_contributions"),
                func.coalesce(sponsored.c.count, 0).label("sponsored_contributions"),
            )
            .outerjoin(authored, authored.c.user_id == SqlUser.id)
            .outerjoin(sponsored, sponsored.c.user_id == SqlUser.id)
        )

    @persistence_boundary
    def by_username(self, username: str) -> PublicResearcher | None:
        row = (
            self._session.execute(self._query().where(SqlUser.username == username))
            .mappings()
            .one_or_none()
        )
        return PublicResearcher(**row) if row else None
