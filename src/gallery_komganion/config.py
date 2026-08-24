from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CONFIG_PATH_ENVIRONMENT_VARIABLE = "GALLERY_KOMGANION_CONFIG_PATH"


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)


class StorageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_path: Path = Path("./data/gallery-komganion.sqlite3")
    thumbnail_directory: Path = Path("./data/thumbnails")


class GalleryRootConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str = Field(min_length=1)
    path: Path
    trash_path: Path
    enabled: bool = True


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server: ServerConfig = ServerConfig()
    storage: StorageConfig = StorageConfig()
    gallery_roots: list[GalleryRootConfig] = Field(default_factory=list)


@dataclass(frozen=True)
class RootAvailability:
    root_id: UUID
    available: bool
    error: str | None = None


def _resolve_path(path: Path, config_directory: Path) -> Path:
    expanded = path.expanduser()

    if not expanded.is_absolute():
        expanded = config_directory / expanded

    return expanded.resolve(strict=False)


def _validate_root_layout(root: GalleryRootConfig) -> None:
    gallery_path = root.path
    trash_path = root.trash_path

    if gallery_path == trash_path:
        raise ValueError(f"Gallery root {root.name!r} cannot use itself as its trash directory")

    if trash_path.is_relative_to(gallery_path):
        raise ValueError(
            f"Trash directory for gallery root {root.name!r} cannot be inside the gallery root"
        )

    if gallery_path.is_relative_to(trash_path):
        raise ValueError(f"Gallery root {root.name!r} cannot be inside its trash directory")

    gallery_drive = gallery_path.drive.casefold()
    trash_drive = trash_path.drive.casefold()

    if gallery_drive and trash_drive and gallery_drive != trash_drive:
        raise ValueError(
            f"Gallery root {root.name!r} and its trash directory must be on the same drive"
        )


def _resolve_config_paths(
    config: AppConfig,
    config_directory: Path,
) -> AppConfig:
    storage = config.storage.model_copy(
        update={
            "database_path": _resolve_path(
                config.storage.database_path,
                config_directory,
            ),
            "thumbnail_directory": _resolve_path(
                config.storage.thumbnail_directory,
                config_directory,
            ),
        }
    )

    gallery_roots: list[GalleryRootConfig] = []

    for root in config.gallery_roots:
        resolved_root = root.model_copy(
            update={
                "path": _resolve_path(root.path, config_directory),
                "trash_path": _resolve_path(root.trash_path, config_directory),
            }
        )
        _validate_root_layout(resolved_root)
        gallery_roots.append(resolved_root)

    return config.model_copy(
        update={
            "storage": storage,
            "gallery_roots": gallery_roots,
        }
    )


def load_config(config_path: str | Path | None = None) -> AppConfig:
    configured_path = (
        config_path or os.environ.get(CONFIG_PATH_ENVIRONMENT_VARIABLE) or "config.toml"
    )

    path = Path(configured_path).expanduser().resolve(strict=False)

    if not path.exists():
        raise FileNotFoundError(f"Gallery Komganion configuration file was not found: {path}")

    if not path.is_file():
        raise ValueError(f"Gallery Komganion configuration path is not a file: {path}")

    with path.open("rb") as config_file:
        raw_config: dict[str, Any] = tomllib.load(config_file)

    parsed_config = AppConfig.model_validate(raw_config)
    return _resolve_config_paths(parsed_config, path.parent)


def check_root_availability(root: GalleryRootConfig) -> RootAvailability:
    if not root.enabled:
        return RootAvailability(
            root_id=root.id,
            available=False,
            error="Gallery root is disabled",
        )

    try:
        if not root.path.exists():
            return RootAvailability(
                root_id=root.id,
                available=False,
                error="Gallery root does not exist",
            )

        if not root.path.is_dir():
            return RootAvailability(
                root_id=root.id,
                available=False,
                error="Gallery root is not a directory",
            )
    except OSError as exc:
        return RootAvailability(
            root_id=root.id,
            available=False,
            error=str(exc),
        )

    return RootAvailability(root_id=root.id, available=True)
