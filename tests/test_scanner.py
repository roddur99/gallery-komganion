from pathlib import Path
from uuid import UUID

from gallery_komganion.config import GalleryRootConfig
from gallery_komganion.services.scanner import (
    discover_galleries,
    is_supported_image,
)

ROOT_ID = UUID("55280de7-869f-4898-b48b-dc519de969bc")


def make_root(path: Path) -> GalleryRootConfig:
    return GalleryRootConfig(
        id=ROOT_ID,
        name="Test Galleries",
        path=path,
        trash_path=path.parent / "trash",
        enabled=True,
    )


def write_image(path: Path, content: bytes = b"image") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_supported_image_extensions_are_case_insensitive() -> None:
    for filename in [
        "page.jpg",
        "page.JPEG",
        "page.Png",
        "page.GIF",
        "page.WEBP",
    ]:
        assert is_supported_image(filename)

    assert not is_supported_image("notes.txt")
    assert not is_supported_image("archive.cbz")


def test_directory_with_direct_images_becomes_gallery(
    tmp_path: Path,
) -> None:
    root = tmp_path / "galleries"
    write_image(root / "Artist" / "Gallery" / "1.jpg")
    write_image(root / "Artist" / "Gallery" / "2.jpg")

    result = discover_galleries(make_root(root))

    assert result.root_available
    assert result.errors == ()
    assert len(result.galleries) == 1

    gallery = result.galleries[0]

    assert gallery.title == "Gallery"
    assert gallery.relative_path == "Artist/Gallery"
    assert gallery.category_path == ("Artist",)
    assert gallery.page_count == 2


def test_pages_are_naturally_sorted(tmp_path: Path) -> None:
    root = tmp_path / "galleries"
    gallery = root / "Gallery"

    for filename in ["10.jpg", "2.jpg", "1.jpg"]:
        write_image(gallery / filename)

    result = discover_galleries(make_root(root))

    assert [page.filename for page in result.galleries[0].pages] == [
        "1.jpg",
        "2.jpg",
        "10.jpg",
    ]


def test_non_image_files_are_ignored(tmp_path: Path) -> None:
    root = tmp_path / "galleries"
    gallery = root / "Gallery"
    write_image(gallery / "1.jpg")
    write_image(gallery / "notes.txt")
    write_image(gallery / "archive.cbz")

    result = discover_galleries(make_root(root))

    assert result.galleries[0].page_count == 1
    assert result.galleries[0].pages[0].filename == "1.jpg"


def test_parent_and_child_can_both_be_galleries(
    tmp_path: Path,
) -> None:
    root = tmp_path / "galleries"
    write_image(root / "Artist" / "cover.jpg")
    write_image(root / "Artist" / "Child Gallery" / "1.jpg")

    result = discover_galleries(make_root(root))

    assert [gallery.relative_path for gallery in result.galleries] == [
        "Artist",
        "Artist/Child Gallery",
    ]


def test_category_only_directories_are_not_galleries(
    tmp_path: Path,
) -> None:
    root = tmp_path / "galleries"
    write_image(root / "Category" / "Gallery" / "1.jpg")

    result = discover_galleries(make_root(root))

    assert [gallery.relative_path for gallery in result.galleries] == ["Category/Gallery"]


def test_gallery_id_survives_rename(tmp_path: Path) -> None:
    root = tmp_path / "galleries"
    original = root / "Original Name"
    write_image(original / "1.jpg")

    first_result = discover_galleries(make_root(root))
    first_id = first_result.galleries[0].id

    renamed = root / "Renamed Gallery"
    original.rename(renamed)

    second_result = discover_galleries(make_root(root))

    assert second_result.galleries[0].id == first_id
    assert second_result.galleries[0].relative_path == "Renamed Gallery"


def test_unavailable_root_returns_error_instead_of_raising(
    tmp_path: Path,
) -> None:
    root = tmp_path / "missing"

    result = discover_galleries(make_root(root))

    assert not result.root_available
    assert result.galleries == ()
    assert len(result.errors) == 1
    assert result.errors[0].message == ("Gallery root does not exist")


def test_gallery_at_root_is_supported(tmp_path: Path) -> None:
    root = tmp_path / "galleries"
    write_image(root / "1.jpg")

    result = discover_galleries(make_root(root))

    assert result.galleries[0].relative_path == "."
    assert result.galleries[0].category_path == ()
