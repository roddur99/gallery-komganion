import shutil
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from gallery_komganion.config import GalleryRootConfig
from gallery_komganion.database import (
    Base,
    create_session_factory,
    create_sqlite_engine,
)
from gallery_komganion.models import (
    Gallery,
    GalleryRoot,
    GalleryStatus,
    Page,
)
from gallery_komganion.services.scanner import (
    DiscoveryResult,
    ScanError,
    discover_galleries,
    synchronize_discovery,
)

ROOT_ID = UUID("55280de7-869f-4898-b48b-dc519de969bc")


@pytest.fixture
def database(
    tmp_path: Path,
) -> tuple[Engine, sessionmaker[Session]]:
    engine = create_sqlite_engine(tmp_path / "test.sqlite3")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)

    yield engine, factory

    engine.dispose()


def make_root(path: Path) -> GalleryRootConfig:
    return GalleryRootConfig(
        id=ROOT_ID,
        name="Test Galleries",
        path=path,
        trash_path=path.parent / "trash",
        enabled=True,
    )


def write_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"image")


def test_discovery_is_synchronized_to_database(
    tmp_path: Path,
    database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = database
    root_path = tmp_path / "galleries"
    write_image(root_path / "Artist" / "Gallery" / "2.jpg")
    write_image(root_path / "Artist" / "Gallery" / "1.jpg")

    configured_root = make_root(root_path)
    discovery = discover_galleries(configured_root)

    with factory.begin() as session:
        result = synchronize_discovery(
            session,
            configured_root,
            discovery,
        )

    assert result.created == 1
    assert result.updated == 0
    assert result.indexed_pages == 2

    with factory() as session:
        root = session.get(GalleryRoot, ROOT_ID)
        gallery = session.scalar(select(Gallery))

        assert root is not None
        assert root.available
        assert gallery is not None
        assert gallery.relative_path == "Artist/Gallery"
        assert gallery.page_count == 2
        assert [page.relative_path for page in gallery.pages] == [
            "1.jpg",
            "2.jpg",
        ]
        assert [page.mime_type for page in gallery.pages] == [
            "image/jpeg",
            "image/jpeg",
        ]


def test_rename_updates_existing_gallery(
    tmp_path: Path,
    database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = database
    root_path = tmp_path / "galleries"
    original = root_path / "Original"
    write_image(original / "1.png")

    configured_root = make_root(root_path)

    with factory.begin() as session:
        synchronize_discovery(
            session,
            configured_root,
            discover_galleries(configured_root),
        )

    renamed = root_path / "Renamed"
    original.rename(renamed)

    with factory.begin() as session:
        result = synchronize_discovery(
            session,
            configured_root,
            discover_galleries(configured_root),
        )

    assert result.created == 0
    assert result.updated == 1

    with factory() as session:
        galleries = session.scalars(select(Gallery)).all()

        assert len(galleries) == 1
        assert galleries[0].relative_path == "Renamed"


def test_removed_gallery_is_marked_missing(
    tmp_path: Path,
    database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = database
    root_path = tmp_path / "galleries"
    gallery_path = root_path / "Gallery"
    write_image(gallery_path / "1.webp")

    configured_root = make_root(root_path)

    with factory.begin() as session:
        synchronize_discovery(
            session,
            configured_root,
            discover_galleries(configured_root),
        )

    shutil.rmtree(gallery_path)

    with factory.begin() as session:
        result = synchronize_discovery(
            session,
            configured_root,
            discover_galleries(configured_root),
        )

    assert result.marked_missing == 1

    with factory() as session:
        gallery = session.scalar(select(Gallery))

        assert gallery is not None
        assert gallery.status == GalleryStatus.MISSING


def test_unavailable_root_does_not_mark_galleries_missing(
    tmp_path: Path,
    database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = database
    root_path = tmp_path / "galleries"
    write_image(root_path / "Gallery" / "1.jpg")

    configured_root = make_root(root_path)

    with factory.begin() as session:
        synchronize_discovery(
            session,
            configured_root,
            discover_galleries(configured_root),
        )

    shutil.rmtree(root_path)
    unavailable_discovery = discover_galleries(configured_root)

    with factory.begin() as session:
        result = synchronize_discovery(
            session,
            configured_root,
            unavailable_discovery,
        )

    assert result.marked_missing == 0

    with factory() as session:
        root = session.get(GalleryRoot, ROOT_ID)
        gallery = session.scalar(select(Gallery))

        assert root is not None
        assert not root.available
        assert gallery is not None
        assert gallery.status == GalleryStatus.ACTIVE


def test_scan_errors_prevent_missing_transition(
    tmp_path: Path,
    database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = database
    root_path = tmp_path / "galleries"
    write_image(root_path / "Gallery" / "1.jpg")

    configured_root = make_root(root_path)

    with factory.begin() as session:
        synchronize_discovery(
            session,
            configured_root,
            discover_galleries(configured_root),
        )

    incomplete_discovery = DiscoveryResult(
        root_id=ROOT_ID,
        root_available=True,
        galleries=(),
        errors=(
            ScanError(
                relative_path="Gallery",
                message="Access denied",
            ),
        ),
    )

    with factory.begin() as session:
        result = synchronize_discovery(
            session,
            configured_root,
            incomplete_discovery,
        )

    assert result.marked_missing == 0

    with factory() as session:
        gallery = session.scalar(select(Gallery))

        assert gallery is not None
        assert gallery.status == GalleryStatus.ACTIVE


def test_rescan_replaces_changed_pages(
    tmp_path: Path,
    database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = database
    root_path = tmp_path / "galleries"
    gallery_path = root_path / "Gallery"
    write_image(gallery_path / "1.jpg")

    configured_root = make_root(root_path)

    with factory.begin() as session:
        synchronize_discovery(
            session,
            configured_root,
            discover_galleries(configured_root),
        )

    write_image(gallery_path / "2.jpg")

    with factory.begin() as session:
        synchronize_discovery(
            session,
            configured_root,
            discover_galleries(configured_root),
        )

    with factory() as session:
        pages = session.scalars(select(Page).order_by(Page.page_index)).all()

        assert [page.relative_path for page in pages] == [
            "1.jpg",
            "2.jpg",
        ]
