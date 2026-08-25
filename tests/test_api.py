from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from gallery_komganion.database import (
    Base,
    create_session_factory,
    create_sqlite_engine,
)
from gallery_komganion.dependencies import get_session
from gallery_komganion.main import app
from gallery_komganion.models import (
    Gallery,
    GalleryRoot,
    Page,
)

ROOT_ID = UUID("55280de7-869f-4898-b48b-dc519de969bc")
FIRST_GALLERY_ID = UUID("bb32cc04-8120-4bb5-91b2-abfb4cc61d80")
SECOND_GALLERY_ID = UUID("078a3d0d-c52b-4855-bc07-ece0796ca669")


@pytest.fixture
def api_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    engine = create_sqlite_engine(tmp_path / "test.sqlite3")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)

    gallery_root = tmp_path / "galleries"
    seed_database(factory, gallery_root)

    def override_session() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    engine.dispose()


def seed_database(
    factory: sessionmaker[Session],
    gallery_root: Path,
) -> None:
    now = datetime.now(UTC)

    first_directory = gallery_root / "Artists" / "Alice" / "Beach Set"
    second_directory = gallery_root / "Artists" / "Bob" / "City Set"

    first_directory.mkdir(parents=True)
    second_directory.mkdir(parents=True)

    (first_directory / "1.jpg").write_bytes(b"first image")
    (first_directory / "2.png").write_bytes(b"second image")
    (second_directory / "1.webp").write_bytes(b"city image")

    with factory.begin() as session:
        root = GalleryRoot(
            id=ROOT_ID,
            name="Test Root",
            path=gallery_root.as_posix(),
            trash_path="C:/Trash",
            available=True,
        )

        first_gallery = Gallery(
            id=FIRST_GALLERY_ID,
            root=root,
            relative_path="Artists/Alice/Beach Set",
            title="Beach Set",
            page_count=2,
            modified_at=now,
            detected_at=now,
            last_scanned_at=now,
        )
        first_gallery.pages = [
            Page(
                page_index=0,
                relative_path="1.jpg",
                size_bytes=11,
                modified_ns=1,
                mime_type="image/jpeg",
            ),
            Page(
                page_index=1,
                relative_path="2.png",
                size_bytes=12,
                modified_ns=2,
                mime_type="image/png",
            ),
        ]

        second_gallery = Gallery(
            id=SECOND_GALLERY_ID,
            root=root,
            relative_path="Artists/Bob/City Set",
            title="City Set",
            page_count=1,
            modified_at=now,
            detected_at=now,
            last_scanned_at=now,
        )
        second_gallery.pages = [
            Page(
                page_index=0,
                relative_path="1.webp",
                size_bytes=10,
                modified_ns=1,
                mime_type="image/webp",
            )
        ]

        session.add(root)
        session.add_all([first_gallery, second_gallery])


def test_health_endpoint(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_galleries(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/galleries")

    assert response.status_code == 200

    payload = response.json()

    assert payload["total"] == 2
    assert payload["limit"] == 50
    assert payload["offset"] == 0
    assert [item["title"] for item in payload["items"]] == [
        "Beach Set",
        "City Set",
    ]
    assert payload["items"][0]["categoryPath"] == [
        "Artists",
        "Alice",
    ]
    assert "relativePath" in payload["items"][0]
    assert "pageCount" in payload["items"][0]


def test_search_galleries(api_client: TestClient) -> None:
    response = api_client.get(
        "/api/v1/galleries",
        params={"query": "beach"},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["title"] == "Beach Set"


def test_gallery_detail(api_client: TestClient) -> None:
    response = api_client.get(f"/api/v1/galleries/{FIRST_GALLERY_ID}")

    assert response.status_code == 200

    payload = response.json()

    assert payload["id"] == str(FIRST_GALLERY_ID)
    assert payload["title"] == "Beach Set"
    assert payload["pageCount"] == 2
    assert payload["categoryPath"] == [
        "Artists",
        "Alice",
    ]
    assert payload["lastScannedAt"] is not None


def test_missing_gallery_returns_404(
    api_client: TestClient,
) -> None:
    response = api_client.get("/api/v1/galleries/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    assert response.status_code == 404


def test_invalid_gallery_id_returns_422(
    api_client: TestClient,
) -> None:
    response = api_client.get("/api/v1/galleries/not-a-uuid")

    assert response.status_code == 422


def test_pagination(api_client: TestClient) -> None:
    response = api_client.get(
        "/api/v1/galleries",
        params={"limit": 1, "offset": 1},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["title"] == "City Set"


def test_list_gallery_pages(api_client: TestClient) -> None:
    response = api_client.get(f"/api/v1/galleries/{FIRST_GALLERY_ID}/pages")

    assert response.status_code == 200

    payload = response.json()

    assert payload["galleryId"] == str(FIRST_GALLERY_ID)
    assert [item["pageIndex"] for item in payload["items"]] == [
        0,
        1,
    ]
    assert [item["filename"] for item in payload["items"]] == [
        "1.jpg",
        "2.png",
    ]
    assert payload["items"][0]["mimeType"] == "image/jpeg"
    assert payload["items"][0]["imageUrl"].endswith(f"/{FIRST_GALLERY_ID}/pages/0")


def test_stream_gallery_page(api_client: TestClient) -> None:
    response = api_client.get(f"/api/v1/galleries/{FIRST_GALLERY_ID}/pages/0")

    assert response.status_code == 200
    assert response.content == b"first image"
    assert response.headers["content-type"] == "image/jpeg"


def test_missing_page_returns_404(
    api_client: TestClient,
) -> None:
    response = api_client.get(f"/api/v1/galleries/{FIRST_GALLERY_ID}/pages/99")

    assert response.status_code == 404


def test_negative_page_returns_404(
    api_client: TestClient,
) -> None:
    response = api_client.get(f"/api/v1/galleries/{FIRST_GALLERY_ID}/pages/-1")

    assert response.status_code == 404
