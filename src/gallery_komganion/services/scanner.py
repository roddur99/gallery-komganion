from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

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

SUPPORTED_IMAGE_EXTENSIONS = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
    }
)


@dataclass(frozen=True)
class DiscoveredPage:
    index: int
    filename: str
    size_bytes: int
    modified_ns: int


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
            )
        )

    # Reassign indexes if a file disappeared between listing and stat.
    return tuple(
        DiscoveredPage(
            index=index,
            filename=page.filename,
            size_bytes=page.size_bytes,
            modified_ns=page.modified_ns,
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
