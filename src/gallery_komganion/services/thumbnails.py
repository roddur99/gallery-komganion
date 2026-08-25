from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID, uuid4

from PIL import Image, ImageOps

SUPPORTED_THUMBNAIL_SIZES = frozenset({256, 512, 1024})


def thumbnail_cache_path(
    thumbnail_directory: Path,
    gallery_id: UUID,
    page_index: int,
    modified_ns: int,
    size: int,
) -> Path:
    if size not in SUPPORTED_THUMBNAIL_SIZES:
        raise ValueError("Unsupported thumbnail size")

    return thumbnail_directory / str(size) / str(gallery_id) / f"{page_index}-{modified_ns}.webp"


def create_thumbnail(
    source_path: Path,
    thumbnail_directory: Path,
    gallery_id: UUID,
    page_index: int,
    modified_ns: int,
    size: int,
) -> Path:
    destination = thumbnail_cache_path(
        thumbnail_directory,
        gallery_id,
        page_index,
        modified_ns,
        size,
    )

    if destination.is_file():
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")

    try:
        with Image.open(source_path) as source:
            thumbnail = ImageOps.exif_transpose(source)
            thumbnail.thumbnail(
                (size, size),
                Image.Resampling.LANCZOS,
            )

            if thumbnail.mode not in {"RGB", "RGBA"}:
                thumbnail = thumbnail.convert("RGBA")

            thumbnail.save(
                temporary_path,
                format="WEBP",
                quality=85,
                method=4,
            )

        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)

    return destination
