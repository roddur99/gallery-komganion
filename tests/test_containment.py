from pathlib import Path

import pytest

from gallery_komganion.filesystem.containment import (
    UnsafePathError,
    safe_join,
    stored_relative_path,
)


def test_safe_join_returns_file_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "galleries"
    gallery = root / "Artist" / "Gallery"
    gallery.mkdir(parents=True)

    image = gallery / "1.jpg"
    image.write_bytes(b"test")

    result = safe_join(root, "Artist/Gallery/1.jpg")

    assert result == image.resolve()


def test_safe_join_rejects_parent_traversal(tmp_path: Path) -> None:
    root = tmp_path / "galleries"
    root.mkdir()

    with pytest.raises(UnsafePathError, match="traversal"):
        safe_join(root, "../secret.txt", must_exist=False)


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "/etc/passwd",
        "C:/Windows/System32/config",
        "C:relative-drive-path",
        "//server/share/file.jpg",
        "gallery\\image.jpg",
        "gallery/image.jpg:secret",
        "",
    ],
)
def test_safe_join_rejects_unsafe_path_forms(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    root = tmp_path / "galleries"
    root.mkdir()

    with pytest.raises(UnsafePathError):
        safe_join(root, unsafe_path, must_exist=False)


def test_safe_join_allows_missing_destination_inside_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "galleries"
    root.mkdir()

    result = safe_join(
        root,
        "Artist/New Gallery",
        must_exist=False,
    )

    assert result == (root / "Artist" / "New Gallery").resolve()


def test_sibling_prefix_is_not_considered_contained(
    tmp_path: Path,
) -> None:
    root = tmp_path / "gallery"
    root.mkdir()

    sibling = tmp_path / "gallery-secret"
    sibling.mkdir()

    with pytest.raises(UnsafePathError):
        stored_relative_path(root, sibling)


def test_stored_relative_path_uses_forward_slashes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "galleries"
    gallery = root / "Artist" / "Gallery"
    gallery.mkdir(parents=True)

    result = stored_relative_path(root, gallery)

    assert result == "Artist/Gallery"


def test_gallery_root_itself_can_be_stored(tmp_path: Path) -> None:
    root = tmp_path / "galleries"
    root.mkdir()

    assert stored_relative_path(root, root) == "."
    assert safe_join(root, ".") == root.resolve()


def test_safe_join_rejects_symlink(
    tmp_path: Path,
) -> None:
    root = tmp_path / "galleries"
    root.mkdir()

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.jpg").write_bytes(b"secret")

    link = root / "linked-gallery"

    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symbolic links is not permitted on this system")

    with pytest.raises(UnsafePathError, match="Symbolic links"):
        safe_join(root, "linked-gallery/secret.jpg")
