from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from gallery_komganion.dependencies import get_session
from gallery_komganion.models import Gallery, GalleryStatus
from gallery_komganion.schemas import (
    GalleryDetail,
    GalleryListResponse,
    GallerySummary,
)

router = APIRouter(
    prefix="/galleries",
    tags=["galleries"],
)

SessionDependency = Annotated[Session, Depends(get_session)]
GallerySort = Literal[
    "title",
    "modifiedAt",
    "createdAt",
    "recentlyDetected",
]
SortDirection = Literal["asc", "desc"]


def _category_path(relative_path: str) -> list[str]:
    if relative_path == ".":
        return []

    path = PurePosixPath(relative_path)
    return list(path.parts[:-1])


def _gallery_summary(gallery: Gallery) -> GallerySummary:
    return GallerySummary(
        id=gallery.id,
        title=gallery.title,
        relative_path=gallery.relative_path,
        category_path=_category_path(gallery.relative_path),
        page_count=gallery.page_count,
        modified_at=gallery.modified_at,
        detected_at=gallery.detected_at,
        status=gallery.status.value,
        can_delete=gallery.status == GalleryStatus.ACTIVE,
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _sort_expression(
    sort: GallerySort,
):
    if sort == "title":
        return func.lower(Gallery.title)

    if sort == "modifiedAt":
        return Gallery.modified_at

    if sort == "createdAt":
        return Gallery.created_at

    return Gallery.detected_at


@router.get("", response_model=GalleryListResponse)
def list_galleries(
    session: SessionDependency,
    query: Annotated[
        str | None,
        Query(min_length=1, max_length=200),
    ] = None,
    sort: Annotated[GallerySort, Query()] = "title",
    direction: Annotated[SortDirection, Query()] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> GalleryListResponse:
    filters = [Gallery.status == GalleryStatus.ACTIVE]

    if query is not None:
        escaped_query = _escape_like(query.casefold())
        filters.append(
            func.lower(Gallery.title).like(
                f"%{escaped_query}%",
                escape="\\",
            )
        )

    order_expression = _sort_expression(sort)

    if direction == "desc":
        order_expression = order_expression.desc()
    else:
        order_expression = order_expression.asc()

    statement: Select[tuple[Gallery]] = (
        select(Gallery)
        .where(*filters)
        .order_by(order_expression, Gallery.id)
        .offset(offset)
        .limit(limit)
    )

    galleries = session.scalars(statement).all()

    total = session.scalar(select(func.count()).select_from(Gallery).where(*filters))

    return GalleryListResponse(
        items=[_gallery_summary(gallery) for gallery in galleries],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{gallery_id}",
    response_model=GalleryDetail,
)
def get_gallery(
    gallery_id: UUID,
    session: SessionDependency,
) -> GalleryDetail:
    gallery = session.get(Gallery, gallery_id)

    if gallery is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gallery not found",
        )

    summary = _gallery_summary(gallery)

    return GalleryDetail(
        **summary.model_dump(),
        last_scanned_at=gallery.last_scanned_at,
    )
