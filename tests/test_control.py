from pathlib import Path
from uuid import UUID

from sqlalchemy import inspect

from gallery_komganion.config import (
    AppConfig,
    GalleryRootConfig,
    StorageConfig,
)
from gallery_komganion.control import ensure_database, scan_config
from gallery_komganion.database import create_sqlite_engine

ROOT_ID = UUID("55280de7-869f-4898-b48b-dc519de969bc")


def make_config(tmp_path: Path) -> AppConfig:
    gallery_path = tmp_path / "galleries"
    trash_path = tmp_path / "trash"

    return AppConfig(
        storage=StorageConfig(
            database_path=tmp_path / "data" / "desktop.sqlite3",
            thumbnail_directory=tmp_path / "data" / "thumbnails",
        ),
        gallery_roots=[
            GalleryRootConfig(
                id=ROOT_ID,
                name="Desktop Galleries",
                path=gallery_path,
                trash_path=trash_path,
            )
        ],
    )


def test_ensure_database_creates_schema_and_directories(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    ensure_database(config)

    assert config.storage.database_path.exists()
    assert config.storage.thumbnail_directory.is_dir()

    engine = create_sqlite_engine(config.storage.database_path)

    try:
        table_names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert {"gallery_roots", "galleries", "pages"} <= table_names


def test_scan_config_returns_combined_summary(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    gallery = config.gallery_roots[0].path / "Artist" / "Set"
    gallery.mkdir(parents=True)
    (gallery / "1.jpg").write_bytes(b"image")
    messages: list[str] = []

    result = scan_config(config, progress=messages.append)

    assert result.roots_scanned == 1
    assert result.created == 1
    assert result.updated == 0
    assert result.indexed_pages == 1
    assert result.errors == ()
    assert messages[0].startswith("Scanning Desktop Galleries")
