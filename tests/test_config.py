from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from gallery_komganion.config import (
    CONFIG_PATH_ENVIRONMENT_VARIABLE,
    check_root_availability,
    load_config,
)

ROOT_ID = "55280de7-869f-4898-b48b-dc519de969bc"


def write_config(path: Path, extra: str = "") -> None:
    path.write_text(
        f"""
[server]
host = "127.0.0.1"
port = 8000

[storage]
database_path = "./data/gallery-komganion.sqlite3"
thumbnail_directory = "./data/thumbnails"

[[gallery_roots]]
id = "{ROOT_ID}"
name = "Test Galleries"
path = "./galleries"
trash_path = "./trash"
enabled = true

{extra}
""".strip(),
        encoding="utf-8",
    )


def test_load_config_resolves_relative_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    config = load_config(config_path)

    assert (
        config.storage.database_path == (tmp_path / "data" / "gallery-komganion.sqlite3").resolve()
    )
    assert config.storage.thumbnail_directory == (tmp_path / "data" / "thumbnails").resolve()

    root = config.gallery_roots[0]

    assert root.id == UUID(ROOT_ID)
    assert root.path == (tmp_path / "galleries").resolve()
    assert root.trash_path == (tmp_path / "trash").resolve()


def test_environment_variable_selects_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "custom.toml"
    write_config(config_path)

    monkeypatch.setenv(
        CONFIG_PATH_ENVIRONMENT_VARIABLE,
        str(config_path),
    )

    config = load_config()

    assert config.gallery_roots[0].name == "Test Galleries"


def test_missing_config_raises_file_not_found(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.toml"

    with pytest.raises(FileNotFoundError):
        load_config(missing_path)


def test_unknown_config_field_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path, extra="unexpected_setting = true")

    with pytest.raises(ValidationError):
        load_config(config_path)


def test_trash_directory_inside_gallery_root_is_rejected(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
[storage]
database_path = "./data/database.sqlite3"
thumbnail_directory = "./data/thumbnails"

[[gallery_roots]]
id = "{ROOT_ID}"
name = "Unsafe Root"
path = "./galleries"
trash_path = "./galleries/trash"
enabled = true
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="cannot be inside"):
        load_config(config_path)


def test_unavailable_root_does_not_raise(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    root = load_config(config_path).gallery_roots[0]
    availability = check_root_availability(root)

    assert availability.available is False
    assert availability.error == "Gallery root does not exist"


def test_available_root_is_reported(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    gallery_directory = tmp_path / "galleries"
    gallery_directory.mkdir()

    root = load_config(config_path).gallery_roots[0]
    availability = check_root_availability(root)

    assert availability.available is True
    assert availability.error is None
