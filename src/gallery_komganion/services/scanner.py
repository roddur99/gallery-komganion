from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from gallery_komganion.config import (
    GalleryRootConfig,
    check_root_availability,
)
from gallery_komganion.filesystem.containment import (
    canonicalize_approved_root,
    stored_relative_path,
)
from gallery_komganion.filesystem.identity import (
    get_or_create_gallery_id,
)
from gallery_komganion.filesystem.natural_sort import (
    naturally_sorted,
)
from gallery_komganion.models import (
    Gallery,
    GalleryRoot,
    GalleryStatus,
    Page,
)

SUPPORTED_IMAGE_EXTENSIONS = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
    }
)

IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


@dataclass(frozen=True)
class DiscoveredPage:
    index: int
    filename: str
    size_bytes: int
    modified_ns: int
    mime_type: str


@dataclass(frozen=True)
class DiscoveredGallery:
    id: UUID
    title: str
    relative_path: str
    category_path: tuple[str, ...]
    pages: tuple[DiscoveredPage, ...]
    modified_at: datetime

    @property
    def page_count(self) -> int:
        return len(self.pages)


@dataclass(frozen=True)
class ScanError:
    relative_path: str
    message: str


@dataclass(frozen=True)
class DiscoveryResult:
    root_id: UUID
    root_available: bool
    galleries: tuple[DiscoveredGallery, ...]
    errors: tuple[ScanError, ...]


@dataclass(frozen=True)
class SynchronizationResult:
    root_id: UUID
    created: int
    updated: int
    marked_missing: int
    indexed_pages: int
    errors: tuple[str, ...]


def is_supported_image(path: str | Path) -> bool:
    return Path(path).suffix.casefold() in SUPPORTED_IMAGE_EXTENSIONS


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False

    reparse_flag = getattr(
        stat,
        "FILE_ATTRIBUTE_REPARSE_POINT",
        0x400,
    )
    file_attributes = getattr(
        metadata,
        "st_file_attributes",
        0,
    )

    return path.is_symlink() or bool(file_attributes & reparse_flag)


def _relative_for_error(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return "<outside-root>"

    if relative == Path("."):
        return "."

    return relative.as_posix()


def _discover_pages(
    root: Path,
    directory: Path,
    filenames: list[str],
    errors: list[ScanError],
) -> tuple[DiscoveredPage, ...]:
    image_paths: list[Path] = []

    for filename in filenames:
        path = directory / filename

        if not is_supported_image(path):
            continue

        try:
            if _is_reparse_point(path):
                errors.append(
                    ScanError(
                        relative_path=_relative_for_error(
                            root,
                            path,
                        ),
                        message=("Skipped image because it is a symbolic link or reparse point"),
                    )
                )
                continue

            if path.is_file():
                image_paths.append(path)
        except OSError as exc:
            errors.append(
                ScanError(
                    relative_path=_relative_for_error(root, path),
                    message=str(exc),
                )
            )

    pages: list[DiscoveredPage] = []

    for index, path in enumerate(naturally_sorted(image_paths)):
        try:
            metadata = path.stat()
        except OSError as exc:
            errors.append(
                ScanError(
                    relative_path=_relative_for_error(root, path),
                    message=str(exc),
                )
            )
            continue

        pages.append(
            DiscoveredPage(
                index=index,
                filename=path.name,
                size_bytes=metadata.st_size,
                modified_ns=metadata.st_mtime_ns,
                mime_type=IMAGE_MIME_TYPES[path.suffix.casefold()],
            )
        )

    # Reassign indexes if a file disappeared between listing and stat.
    return tuple(
        DiscoveredPage(
            index=index,
            filename=page.filename,
            size_bytes=page.size_bytes,
            modified_ns=page.modified_ns,
            mime_type=page.mime_type,
        )
        for index, page in enumerate(pages)
    )


def discover_galleries(
    configured_root: GalleryRootConfig,
) -> DiscoveryResult:
    availability = check_root_availability(configured_root)

    if not availability.available:
        error = availability.error or "Gallery root is unavailable"

        return DiscoveryResult(
            root_id=configured_root.id,
            root_available=False,
            galleries=(),
            errors=(ScanError(relative_path=".", message=error),),
        )

    root = canonicalize_approved_root(configured_root.path)
    galleries: list[DiscoveredGallery] = []
    errors: list[ScanError] = []
    seen_gallery_ids: dict[UUID, str] = {}

    def record_walk_error(error: OSError) -> None:
        filename = error.filename
        path = Path(filename) if filename else root

        errors.append(
            ScanError(
                relative_path=_relative_for_error(root, path),
                message=str(error),
            )
        )

    for directory_name, directory_names, filenames in os.walk(
        root,
        topdown=True,
        onerror=record_walk_error,
        followlinks=False,
    ):
        directory = Path(directory_name)

        safe_directories: list[str] = []

        for child_name in directory_names:
            child = directory / child_name

            if _is_reparse_point(child):
                errors.append(
                    ScanError(
                        relative_path=_relative_for_error(root, child),
                        message=(
                            "Skipped directory because it is a symbolic link or reparse point"
                        ),
                    )
                )
                continue

            safe_directories.append(child_name)

        directory_names[:] = safe_directories

        pages = _discover_pages(
            root,
            directory,
            filenames,
            errors,
        )

        if not pages:
            continue

        relative_path = stored_relative_path(root, directory)

        try:
            gallery_id = get_or_create_gallery_id(directory)
        except (OSError, ValueError) as exc:
            errors.append(
                ScanError(
                    relative_path=relative_path,
                    message=(f"Could not read or create gallery identity: {exc}"),
                )
            )
            continue

        existing_path = seen_gallery_ids.get(gallery_id)

        if existing_path is not None:
            errors.append(
                ScanError(
                    relative_path=relative_path,
                    message=(f"Duplicate gallery ID also used by {existing_path!r}"),
                )
            )
            continue

        seen_gallery_ids[gallery_id] = relative_path

        relative = Path(relative_path)
        category_path = () if relative_path == "." else tuple(relative.parts[:-1])

        newest_modified_ns = max(page.modified_ns for page in pages)

        galleries.append(
            DiscoveredGallery(
                id=gallery_id,
                title=directory.name,
                relative_path=relative_path,
                category_path=category_path,
                pages=pages,
                modified_at=datetime.fromtimestamp(
                    newest_modified_ns / 1_000_000_000,
                    tz=UTC,
                ),
            )
        )

    galleries.sort(key=lambda gallery: gallery.relative_path.casefold())

    return DiscoveryResult(
        root_id=configured_root.id,
        root_available=True,
        galleries=tuple(galleries),
        errors=tuple(errors),
    )


def _summarize_errors(errors: tuple[ScanError, ...]) -> str | None:
    if not errors:
        return None

    displayed = errors[:5]
    summary = "; ".join(f"{error.relative_path}: {error.message}" for error in displayed)

    remaining = len(errors) - len(displayed)

    if remaining > 0:
        summary += f"; and {remaining} more error(s)"

    return summary


def _synchronize_root(
    session: Session,
    configured_root: GalleryRootConfig,
    discovery: DiscoveryResult,
    scanned_at: datetime,
) -> GalleryRoot:
    root = session.get(GalleryRoot, configured_root.id)

    if root is None:
        root = GalleryRoot(
            id=configured_root.id,
            name=configured_root.name,
            path=configured_root.path.as_posix(),
            trash_path=configured_root.trash_path.as_posix(),
        )
        session.add(root)

    root.name = configured_root.name
    root.path = configured_root.path.as_posix()
    root.trash_path = configured_root.trash_path.as_posix()
    root.enabled = configured_root.enabled
    root.available = discovery.root_available
    root.last_scan_at = scanned_at
    root.last_error = _summarize_errors(discovery.errors)

    return root


def synchronize_discovery(
    session: Session,
    configured_root: GalleryRootConfig,
    discovery: DiscoveryResult,
    *,
    scanned_at: datetime | None = None,
) -> SynchronizationResult:
    if discovery.root_id != configured_root.id:
        raise ValueError("Discovery result does not belong to the configured root")

    scan_time = scanned_at or datetime.now(UTC)

    root = _synchronize_root(
        session,
        configured_root,
        discovery,
        scan_time,
    )
    session.flush()

    synchronization_errors: list[str] = []

    if not discovery.root_available:
        return SynchronizationResult(
            root_id=configured_root.id,
            created=0,
            updated=0,
            marked_missing=0,
            indexed_pages=0,
            errors=tuple(error.message for error in discovery.errors),
        )

    existing_galleries = session.scalars(
        select(Gallery).where(Gallery.root_id == configured_root.id)
    ).all()
    existing_by_id = {gallery.id: gallery for gallery in existing_galleries}

    # Temporarily move renamed records out of the unique relative-path
    # namespace. This also supports two galleries swapping directory names.
    renamed_galleries = [
        (existing_by_id[gallery.id], gallery)
        for gallery in discovery.galleries
        if gallery.id in existing_by_id
        and existing_by_id[gallery.id].relative_path != gallery.relative_path
    ]

    for stored_gallery, _ in renamed_galleries:
        stored_gallery.relative_path = f"__pending__:{stored_gallery.id}"

    if renamed_galleries:
        session.flush()

    created = 0
    updated = 0
    indexed_pages = 0
    seen_gallery_ids: set[UUID] = set()

    for discovered in discovery.galleries:
        existing_anywhere = session.get(Gallery, discovered.id)

        if existing_anywhere is not None and existing_anywhere.root_id != configured_root.id:
            synchronization_errors.append(
                f"Gallery ID {discovered.id} is already used by another configured root"
            )
            continue

        gallery = existing_by_id.get(discovered.id)

        if gallery is None:
            gallery = Gallery(
                id=discovered.id,
                root=root,
                relative_path=discovered.relative_path,
                title=discovered.title,
            )
            session.add(gallery)
            created += 1
        else:
            gallery.pages.clear()
            session.flush()
            updated += 1

        gallery.relative_path = discovered.relative_path
        gallery.title = discovered.title
        gallery.status = GalleryStatus.ACTIVE
        gallery.page_count = discovered.page_count
        gallery.modified_at = discovered.modified_at
        gallery.last_scanned_at = scan_time
        gallery.trashed_at = None
        gallery.original_relative_path = None
        gallery.trash_relative_path = None

        gallery.pages.extend(
            Page(
                page_index=page.index,
                relative_path=page.filename,
                size_bytes=page.size_bytes,
                modified_ns=page.modified_ns,
                mime_type=page.mime_type,
            )
            for page in discovered.pages
        )

        indexed_pages += discovered.page_count
        seen_gallery_ids.add(discovered.id)

    marked_missing = 0

    # Any filesystem error can make a gallery temporarily invisible.
    # Only mark missing galleries after a completely successful traversal.
    if not discovery.errors and not synchronization_errors:
        for gallery in existing_galleries:
            if gallery.id not in seen_gallery_ids and gallery.status == GalleryStatus.ACTIVE:
                gallery.status = GalleryStatus.MISSING
                gallery.last_scanned_at = scan_time
                marked_missing += 1

    return SynchronizationResult(
        root_id=configured_root.id,
        created=created,
        updated=updated,
        marked_missing=marked_missing,
        indexed_pages=indexed_pages,
        errors=tuple(synchronization_errors),
    )
