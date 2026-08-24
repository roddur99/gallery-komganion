import json
from pathlib import Path
from uuid import UUID

import pytest

from gallery_komganion.filesystem.identity import (
    SIDECAR_FILENAME,
    InvalidGalleryIdentityError,
    get_or_create_gallery_id,
    read_gallery_id,
)


def test_missing_sidecar_returns_none(tmp_path: Path) -> None:
    gallery = tmp_path / "gallery"
    gallery.mkdir()

    assert read_gallery_id(gallery) is None


def test_gallery_id_is_created_and_remains_stable(
    tmp_path: Path,
) -> None:
    gallery = tmp_path / "gallery"
    gallery.mkdir()

    first_id = get_or_create_gallery_id(gallery)
    second_id = get_or_create_gallery_id(gallery)

    assert isinstance(first_id, UUID)
    assert second_id == first_id
    assert read_gallery_id(gallery) == first_id


def test_created_sidecar_has_expected_content(tmp_path: Path) -> None:
    gallery = tmp_path / "gallery"
    gallery.mkdir()

    gallery_id = get_or_create_gallery_id(gallery)

    payload = json.loads((gallery / SIDECAR_FILENAME).read_text(encoding="utf-8"))

    assert payload == {
        "version": 1,
        "galleryId": str(gallery_id),
    }


def test_existing_valid_sidecar_is_never_replaced(
    tmp_path: Path,
) -> None:
    gallery = tmp_path / "gallery"
    gallery.mkdir()

    existing_id = UUID("55280de7-869f-4898-b48b-dc519de969bc")
    sidecar = gallery / SIDECAR_FILENAME
    original_content = f'{{"version":1,"galleryId":"{existing_id}"}}\n'
    sidecar.write_text(original_content, encoding="utf-8")

    returned_id = get_or_create_gallery_id(gallery)

    assert returned_id == existing_id
    assert sidecar.read_text(encoding="utf-8") == original_content


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        "{}",
        '{"version":1}',
        '{"galleryId":"55280de7-869f-4898-b48b-dc519de969bc"}',
        ('{"version":2,"galleryId":"55280de7-869f-4898-b48b-dc519de969bc"}'),
        '{"version":1,"galleryId":"not-a-uuid"}',
        ('{"version":1,"galleryId":"55280DE7-869F-4898-B48B-DC519DE969BC"}'),
        ('{"version":1,"galleryId":"55280de7-869f-4898-b48b-dc519de969bc","unexpected":true}'),
        ('{"version":1,"version":1,"galleryId":"55280de7-869f-4898-b48b-dc519de969bc"}'),
    ],
)
def test_invalid_sidecars_are_rejected(
    tmp_path: Path,
    content: str,
) -> None:
    gallery = tmp_path / "gallery"
    gallery.mkdir()

    (gallery / SIDECAR_FILENAME).write_text(
        content,
        encoding="utf-8",
    )

    with pytest.raises(InvalidGalleryIdentityError):
        read_gallery_id(gallery)


def test_temporary_files_are_removed(tmp_path: Path) -> None:
    gallery = tmp_path / "gallery"
    gallery.mkdir()

    get_or_create_gallery_id(gallery)

    temporary_files = list(gallery.glob(".gallery-komganion.*.tmp"))

    assert temporary_files == []
