from __future__ import annotations

from enum import IntEnum
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from PIL import UnidentifiedImageError
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from gallery_komganion.config import AppConfig
from gallery_komganion.dependencies import get_config, get_session
from gallery_komganion.filesystem.containment import (
    UnsafePathError,
    safe_join,
)
from gallery_komganion.models import (
    Gallery,
    GalleryRoot,
    GalleryStatus,
    Page,
)
from gallery_komganion.schemas import (
    GalleryDetail,
    GalleryListResponse,
    GallerySummary,
    PageListResponse,
    PageSummary,
)
from gallery_komganion.services.thumbnails import (
    create_thumbnail,
)

router = APIRouter(
    prefix="/galleries",
    tags=["galleries"],
)

SessionDependency = Annotated[Session, Depends(get_session)]
ConfigDependency = Annotated[AppConfig, Depends(get_config)]

GallerySort = Literal[
    "title",
    "modifiedAt",
    "createdAt",
    "recentlyDetected",
]
SortDirection = Literal["asc", "desc"]


class ThumbnailSize(IntEnum):
    SMALL = 256
    MEDIUM = 512
    LARGE = 1024


def _category_path(relative_path: str) -> list[str]:
    if relative_path == ".":
        return []

    path = PurePosixPath(relative_path)
    return list(path.parts[:-1])


def _gallery_cover_url(gallery: Gallery) -> str | None:
    if gallery.page_count < 1:
        return None

    version = int(gallery.modified_at.timestamp() * 1_000_000)

    return f"/api/v1/galleries/{gallery.id}/pages/0/thumbnail?size=512&v={version}"


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
        cover_url=_gallery_cover_url(gallery),
    )


def _get_readable_gallery(
    session: Session,
    gallery_id: UUID,
) -> tuple[Gallery, GalleryRoot]:
    gallery = session.get(Gallery, gallery_id)

    if gallery is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gallery not found",
        )

    if gallery.status != GalleryStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gallery is not currently available",
        )

    root = session.get(GalleryRoot, gallery.root_id)

    if root is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gallery root record is unavailable",
        )

    if not root.available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gallery root is currently offline",
        )

    return gallery, root


def _get_page(
    session: Session,
    gallery: Gallery,
    page_index: int,
) -> Page:
    if page_index < 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Page not found",
        )

    page = session.scalar(
        select(Page).where(
            Page.gallery_id == gallery.id,
            Page.page_index == page_index,
        )
    )

    if page is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Page not found",
        )

    return page


def _resolve_page_path(
    root: GalleryRoot,
    gallery: Gallery,
    page: Page,
) -> Path:
    if gallery.relative_path == ".":
        stored_path = page.relative_path
    else:
        stored_path = f"{gallery.relative_path}/{page.relative_path}"

    try:
        image_path = safe_join(
            root.path,
            stored_path,
            must_exist=True,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Indexed image file was not found",
        ) from exc
    except (UnsafePathError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Indexed image path is unsafe or unavailable",
        ) from exc

    if not image_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Indexed page is not a file",
        )

    return image_path


def _page_image_url(
    gallery_id: UUID,
    page_index: int,
) -> str:
    return f"/api/v1/galleries/{gallery_id}/pages/{page_index}"


def _page_thumbnail_url(
    gallery_id: UUID,
    page: Page,
) -> str:
    return (
        f"/api/v1/galleries/{gallery_id}/pages/"
        f"{page.page_index}/thumbnail"
        f"?size=512&v={page.modified_ns}"
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


@router.get(
    "/{gallery_id}/pages",
    response_model=PageListResponse,
)
def list_gallery_pages(
    gallery_id: UUID,
    session: SessionDependency,
) -> PageListResponse:
    gallery, _ = _get_readable_gallery(
        session,
        gallery_id,
    )

    pages = session.scalars(
        select(Page).where(Page.gallery_id == gallery.id).order_by(Page.page_index)
    ).all()

    return PageListResponse(
        gallery_id=gallery.id,
        items=[
            PageSummary(
                page_index=page.page_index,
                filename=page.relative_path,
                size_bytes=page.size_bytes,
                mime_type=page.mime_type,
                width=page.width,
                height=page.height,
                image_url=_page_image_url(
                    gallery.id,
                    page.page_index,
                ),
                thumbnail_url=_page_thumbnail_url(
                    gallery.id,
                    page,
                ),
            )
            for page in pages
        ],
    )


@router.get(
    "/{gallery_id}/pages/{page_index}/thumbnail",
    response_class=FileResponse,
)
def stream_gallery_thumbnail(
    gallery_id: UUID,
    page_index: int,
    session: SessionDependency,
    config: ConfigDependency,
    size: Annotated[ThumbnailSize, Query()] = (ThumbnailSize.MEDIUM),
) -> FileResponse:
    gallery, root = _get_readable_gallery(
        session,
        gallery_id,
    )
    page = _get_page(
        session,
        gallery,
        page_index,
    )
    image_path = _resolve_page_path(
        root,
        gallery,
        page,
    )

    try:
        thumbnail_path = create_thumbnail(
            source_path=image_path,
            thumbnail_directory=(config.storage.thumbnail_directory),
            gallery_id=gallery.id,
            page_index=page.page_index,
            modified_ns=page.modified_ns,
            size=size,
        )
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Thumbnail could not be generated",
        ) from exc

    return FileResponse(
        path=thumbnail_path,
        media_type="image/webp",
        headers={"Cache-Control": ("private, max-age=31536000, immutable")},
    )


@router.get(
    "/{gallery_id}/pages/{page_index}",
    response_class=FileResponse,
)
def stream_gallery_page(
    gallery_id: UUID,
    page_index: int,
    session: SessionDependency,
) -> FileResponse:
    gallery, root = _get_readable_gallery(
        session,
        gallery_id,
    )
    page = _get_page(
        session,
        gallery,
        page_index,
    )
    image_path = _resolve_page_path(
        root,
        gallery,
        page,
    )

    return FileResponse(
        path=image_path,
        media_type=page.mime_type,
    )
