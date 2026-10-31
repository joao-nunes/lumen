"""SQLAlchemy ORM models.

Every user-owned table carries `user_id`, even when it could be derived via a
parent row. This keeps Row-Level Security policies simple (`user_id = current
user`) and avoids subqueries in every policy. Composite foreign keys
(`(parent_id, user_id)`) guarantee a child row can never point at a parent
owned by a different user.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    MetaData,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from lumen.domain.checkin import CheckinMode
from lumen.domain.dimensions import SCALE_MAX, SCALE_MIN, Dimension

# Deterministic constraint names, so Alembic migrations are stable and readable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _enum(enum_cls: type[Dimension] | type[CheckinMode], name: str) -> Enum:
    # Store the enum *values* ("sleep_quality"), not member names ("SLEEP_QUALITY").
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class User(Base):
    """User identity. Credentials and sessions live in the `auth` schema (lumen.auth.models)."""

    __tablename__ = "users"
    __table_args__ = (
        # Shape check only; real validation happens in the application layer.
        CheckConstraint("email LIKE '%_@_%'", name="email_shape"),
        CheckConstraint("char_length(email) <= 254", name="email_length"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # citext: case-insensitive comparisons, so uniqueness and lookups can't be
    # defeated by capitalisation.
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Checkin(Base):
    __tablename__ = "checkins"
    __table_args__ = (
        # Target for composite foreign keys from child tables.
        UniqueConstraint("id", "user_id"),
        # One check-in per local day (spec 002); its index also serves date-range queries.
        UniqueConstraint("user_id", "local_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    local_date: Mapped[date] = mapped_column(Date)
    mode: Mapped[CheckinMode] = mapped_column(_enum(CheckinMode, "checkin_mode"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    scores: Mapped[list["CheckinScore"]] = relationship(
        back_populates="checkin",
        cascade="all, delete-orphan",
    )
    tags: Mapped[list["CheckinTag"]] = relationship(
        back_populates="checkin",
        cascade="all, delete-orphan",
    )


class CheckinScore(Base):
    __tablename__ = "checkin_scores"
    __table_args__ = (
        ForeignKeyConstraint(
            ["checkin_id", "user_id"],
            ["checkins.id", "checkins.user_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(f"value BETWEEN {SCALE_MIN} AND {SCALE_MAX}", name="value_in_scale"),
    )

    checkin_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    dimension: Mapped[Dimension] = mapped_column(_enum(Dimension, "dimension"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    value: Mapped[int] = mapped_column(SmallInteger)

    checkin: Mapped[Checkin] = relationship(back_populates="scores")


class Tag(Base):
    """User-defined tag vocabulary (e.g. "exercise", "caffeine_late")."""

    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("user_id", "name"),
        UniqueConstraint("id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(40))


class CheckinTag(Base):
    __tablename__ = "checkin_tags"
    __table_args__ = (
        ForeignKeyConstraint(
            ["checkin_id", "user_id"],
            ["checkins.id", "checkins.user_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tag_id", "user_id"],
            ["tags.id", "tags.user_id"],
            ondelete="CASCADE",
        ),
    )

    checkin_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))

    checkin: Mapped[Checkin] = relationship(back_populates="tags")
    # Both relationships write checkin_tags.user_id; the composite foreign keys
    # guarantee the check-in and the tag belong to the same user, so the
    # overlap is intentional.
    tag: Mapped[Tag] = relationship(overlaps="checkin,tags")
