"""Canonical SQLAlchemy declarative base and metadata."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base for canonical Polycolab persistence models."""

    metadata = MetaData()


metadata = Base.metadata
