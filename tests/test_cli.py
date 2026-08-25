from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from gallery_komganion.cli import run_scan
from gallery_komganion.config import (
    AppConfig,
    GalleryRootConfig,
    StorageConfig,
)
from gallery_komganion.database import (
    Base,
    create_session_factory,
    create_sqlite_engine,
)
from gallery_komganion.models import Gallery, GalleryRoot, Page

ROOT_ID = UUID("55280de7-869f-4898-b48b-dc519de969bc")


def make_config(
    tmp_path: Path,
    gallery_path: Path,
    *,
    enabled: bool = True,
) -> AppConfig:
    return AppConfig(
        storage=StorageConfig(
            database_path=tmp_path / "test.sqlite3",
            thumbnail_directory=tmp_path / "thumbnails",
        ),
        gallery_roots=[
            GalleryRootConfig(
                id=ROOT_ID,
                name="Test Galleries",
                path=gallery_path,
                trash_path=tmp_path / "trash",
                enabled=enabled,
            )
        ],
    )


def create_database(database_path: Path) -> None:
    engine = create_sqlite_engine(database_path)

    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()


def test_run_scan_indexes_configured_galleries(
    tmp_path: Path,
) -> None:
    gallery_path = tmp_path / "galleries"
    gallery_directory = gallery_path / "Artist" / "Gallery"
    gallery_directory.mkdir(parents=True)
    (gallery_directory / "1.jpg").write_bytes(b"first")
    (gallery_directory / "2.png").write_bytes(b"second")

    config = make_config(tmp_path, gallery_path)
    create_database(config.storage.database_path)

    exit_code = run_scan(config)

    assert exit_code == 0

    engine = create_sqlite_engine(config.storage.database_path)
    factory = create_session_factory(engine)

    try:
        with factory() as session:
            root = session.get(GalleryRoot, ROOT_ID)
            gallery = session.scalar(select(Gallery))
            pages = session.scalars(select(Page).order_by(Page.page_index)).all()

            assert root is not None
            assert root.available
            assert gallery is not None
            assert gallery.relative_path == "Artist/Gallery"
            assert gallery.page_count == 2
            assert [page.relative_path for page in pages] == [
                "1.jpg",
                "2.png",
            ]
    finally:
        engine.dispose()


def test_run_scan_reports_unavailable_root(
    tmp_path: Path,
) -> None:
    gallery_path = tmp_path / "missing"
    config = make_config(tmp_path, gallery_path)
    create_database(config.storage.database_path)

    exit_code = run_scan(config)

    assert exit_code == 1

    engine = create_sqlite_engine(config.storage.database_path)
    factory = create_session_factory(engine)

    try:
        with factory() as session:
            root = session.get(GalleryRoot, ROOT_ID)

            assert root is not None
            assert not root.available
            assert session.scalars(select(Gallery)).all() == []
    finally:
        engine.dispose()


def test_run_scan_skips_disabled_roots(
    tmp_path: Path,
) -> None:
    gallery_path = tmp_path / "galleries"
    gallery_path.mkdir()

    config = make_config(
        tmp_path,
        gallery_path,
        enabled=False,
    )
    create_database(config.storage.database_path)

    exit_code = run_scan(config)

    assert exit_code == 0

    engine = create_sqlite_engine(config.storage.database_path)
    factory = create_session_factory(engine)

    try:
        with factory() as session:
            assert session.get(GalleryRoot, ROOT_ID) is None
    finally:
        engine.dispose()
