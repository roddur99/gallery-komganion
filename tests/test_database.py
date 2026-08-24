from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from gallery_komganion.database import (
    Base,
    create_session_factory,
    create_sqlite_engine,
    session_scope,
)
from gallery_komganion.models import (
    Gallery,
    GalleryRoot,
    GalleryStatus,
)


@pytest.fixture
def database(
    tmp_path: Path,
) -> tuple[Engine, sessionmaker[Session]]:
    engine = create_sqlite_engine(tmp_path / "test.sqlite3")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)

    yield engine, factory

    engine.dispose()


def test_root_and_gallery_can_be_persisted(
    database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = database
    root_id = uuid4()
    gallery_id = uuid4()

    with factory.begin() as session:
        root = GalleryRoot(
            id=root_id,
            name="Test Root",
            path="C:/Galleries",
            trash_path="C:/GalleryKomganionTrash",
        )
        gallery = Gallery(
            id=gallery_id,
            root=root,
            relative_path="Artist/Gallery",
            title="Gallery",
            page_count=10,
        )

        session.add(root)
        session.add(gallery)

    with factory() as session:
        stored_gallery = session.scalar(select(Gallery).where(Gallery.id == gallery_id))

        assert stored_gallery is not None
        assert stored_gallery.title == "Gallery"
        assert stored_gallery.page_count == 10
        assert stored_gallery.status == GalleryStatus.ACTIVE
        assert stored_gallery.root_id == root_id


def test_duplicate_relative_path_within_root_is_rejected(
    database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = database
    root_id = uuid4()

    with factory.begin() as session:
        session.add(
            GalleryRoot(
                id=root_id,
                name="Test Root",
                path="C:/Galleries",
                trash_path="C:/Trash",
            )
        )

    with pytest.raises(IntegrityError), factory.begin() as session:
        session.add_all(
            [
                Gallery(
                    root_id=root_id,
                    relative_path="Artist/Gallery",
                    title="First",
                ),
                Gallery(
                    root_id=root_id,
                    relative_path="Artist/Gallery",
                    title="Second",
                ),
            ]
        )


def test_same_relative_path_is_allowed_in_different_roots(
    database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = database

    with factory.begin() as session:
        first_root = GalleryRoot(
            id=uuid4(),
            name="First Root",
            path="C:/First",
            trash_path="C:/FirstTrash",
        )
        second_root = GalleryRoot(
            id=uuid4(),
            name="Second Root",
            path="D:/Second",
            trash_path="D:/SecondTrash",
        )

        session.add_all(
            [
                Gallery(
                    root=first_root,
                    relative_path="Gallery",
                    title="First Gallery",
                ),
                Gallery(
                    root=second_root,
                    relative_path="Gallery",
                    title="Second Gallery",
                ),
            ]
        )

    with factory() as session:
        galleries = session.scalars(select(Gallery)).all()

        assert len(galleries) == 2


def test_foreign_keys_are_enabled(
    database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = database

    with pytest.raises(IntegrityError), factory.begin() as session:
        session.add(
            Gallery(
                root_id=uuid4(),
                relative_path="Orphan",
                title="Orphan",
            )
        )


def test_session_scope_commits(
    database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = database
    root_id = uuid4()

    with session_scope(factory) as session:
        session.add(
            GalleryRoot(
                id=root_id,
                name="Test Root",
                path="C:/Galleries",
                trash_path="C:/Trash",
            )
        )

    with factory() as session:
        assert session.get(GalleryRoot, root_id) is not None


def test_session_scope_rolls_back_on_error(
    database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = database
    root_id = uuid4()

    with pytest.raises(RuntimeError, match="failure"), session_scope(factory) as session:
        session.add(
            GalleryRoot(
                id=root_id,
                name="Test Root",
                path="C:/Galleries",
                trash_path="C:/Trash",
            )
        )
        raise RuntimeError("failure")

    with factory() as session:
        assert session.get(GalleryRoot, root_id) is None
