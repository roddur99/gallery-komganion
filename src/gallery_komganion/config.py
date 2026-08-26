from __future__ import annotations

import json
import os
import secrets
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

CONFIG_PATH_ENVIRONMENT_VARIABLE = "GALLERY_KOMGANION_CONFIG_PATH"


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)


class SecurityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_token: SecretStr | None = None


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
    security: SecurityConfig = SecurityConfig()
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


def create_default_config(config_path: str | Path) -> AppConfig:
    path = Path(config_path).expanduser().resolve(strict=False)
    data_directory = path.parent / "data"

    return AppConfig(
        security=SecurityConfig(
            api_token=SecretStr(secrets.token_urlsafe(32)),
        ),
        storage=StorageConfig(
            database_path=data_directory / "gallery-komganion.sqlite3",
            thumbnail_directory=data_directory / "thumbnails",
        ),
    )


def _toml_string(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def save_config(config: AppConfig, config_path: str | Path) -> AppConfig:
    path = Path(config_path).expanduser().resolve(strict=False)
    resolved = _resolve_config_paths(config, path.parent)
    token = resolved.security.api_token
    token_value = token.get_secret_value() if token is not None else ""

    lines = [
        "[server]",
        f"host = {_toml_string(resolved.server.host)}",
        f"port = {resolved.server.port}",
        "",
        "[security]",
        f"api_token = {_toml_string(token_value)}",
        "",
        "[storage]",
        f"database_path = {_toml_string(resolved.storage.database_path.as_posix())}",
        (
            "thumbnail_directory = "
            f"{_toml_string(resolved.storage.thumbnail_directory.as_posix())}"
        ),
    ]

    for root in resolved.gallery_roots:
        lines.extend(
            [
                "",
                "[[gallery_roots]]",
                f"id = {_toml_string(root.id)}",
                f"name = {_toml_string(root.name)}",
                f"path = {_toml_string(root.path.as_posix())}",
                f"trash_path = {_toml_string(root.trash_path.as_posix())}",
                f"enabled = {str(root.enabled).lower()}",
            ]
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary_path.replace(path)

    return resolved


def load_or_create_config(config_path: str | Path) -> AppConfig:
    path = Path(config_path).expanduser().resolve(strict=False)

    if path.exists():
        return load_config(path)

    config = create_default_config(path)
    return save_config(config, path)


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
