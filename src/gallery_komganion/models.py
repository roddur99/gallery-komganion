from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gallery_komganion.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class GalleryStatus(StrEnum):
    ACTIVE = "active"
    MISSING = "missing"
    TRASHED = "trashed"


gallery_status_type = Enum(
    GalleryStatus,
    values_callable=lambda statuses: [status.value for status in statuses],
    native_enum=False,
    create_constraint=True,
    validate_strings=True,
    name="gallery_status",
)


class GalleryRoot(Base):
    __tablename__ = "gallery_roots"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        unique=True,
    )
    trash_path: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    available: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    last_scan_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    galleries: Mapped[list[Gallery]] = relationship(
        back_populates="root",
        cascade="all, delete-orphan",
    )


class Gallery(Base):
    __tablename__ = "galleries"
    __table_args__ = (
        UniqueConstraint(
            "root_id",
            "relative_path",
            name="uq_galleries_root_relative_path",
        ),
        CheckConstraint(
            "page_count >= 0",
            name="ck_galleries_page_count_nonnegative",
        ),
        Index("ix_galleries_status", "status"),
        Index("ix_galleries_title", "title"),
        Index("ix_galleries_detected_at", "detected_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    root_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("gallery_roots.id", ondelete="CASCADE"),
        nullable=False,
    )
    relative_path: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    status: Mapped[GalleryStatus] = mapped_column(
        gallery_status_type,
        nullable=False,
        default=GalleryStatus.ACTIVE,
    )
    page_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    modified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    last_scanned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    content_signature: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    thumbnail_key: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    trashed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    original_relative_path: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    trash_relative_path: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    root: Mapped[GalleryRoot] = relationship(
        back_populates="galleries",
    )
