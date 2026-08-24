from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


def to_camel_case(value: str) -> str:
    first, *remaining = value.split("_")
    return first + "".join(word.capitalize() for word in remaining)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
    )


class GallerySummary(ApiModel):
    id: UUID
    title: str
    relative_path: str
    category_path: list[str]
    page_count: int
    modified_at: datetime
    detected_at: datetime
    status: str
    can_delete: bool


class GalleryDetail(GallerySummary):
    last_scanned_at: datetime | None


class GalleryListResponse(ApiModel):
    items: list[GallerySummary]
    total: int
    limit: int
    offset: int
