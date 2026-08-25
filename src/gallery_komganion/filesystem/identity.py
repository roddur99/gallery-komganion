from __future__ import annotations

import ctypes
import json
import os
import stat
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

SIDECAR_FILENAME = ".gallery-komganion.json"
SIDECAR_VERSION = 1


class InvalidGalleryIdentityError(ValueError):
    """Raised when a gallery identity sidecar is malformed or unsafe."""


def _reject_duplicate_keys(
    pairs: Iterable[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}

    for key, value in pairs:
        if key in result:
            raise InvalidGalleryIdentityError(f"Duplicate key in gallery identity sidecar: {key}")

        result[key] = value

    return result


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False

    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    file_attributes = getattr(metadata, "st_file_attributes", 0)

    return path.is_symlink() or bool(file_attributes & reparse_flag)


def _mark_hidden_on_windows(path: Path) -> None:
    """Best-effort application of the Windows hidden-file attribute."""

    if os.name != "nt":
        return

    file_attribute_hidden = 0x2
    invalid_file_attributes = 0xFFFFFFFF

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    get_attributes = kernel32.GetFileAttributesW
    get_attributes.argtypes = [ctypes.c_wchar_p]
    get_attributes.restype = ctypes.c_uint32

    set_attributes = kernel32.SetFileAttributesW
    set_attributes.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
    set_attributes.restype = ctypes.c_int

    attributes = get_attributes(str(path))

    if attributes == invalid_file_attributes:
        return

    set_attributes(str(path), attributes | file_attribute_hidden)


def _parse_gallery_identity(content: str) -> UUID:
    try:
        payload = json.loads(
            content,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except json.JSONDecodeError as exc:
        raise InvalidGalleryIdentityError("Gallery identity sidecar is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise InvalidGalleryIdentityError("Gallery identity sidecar must contain a JSON object")

    expected_keys = {"version", "galleryId"}

    if set(payload) != expected_keys:
        raise InvalidGalleryIdentityError(
            "Gallery identity sidecar must contain exactly 'version' and 'galleryId'"
        )

    version = payload["version"]

    if type(version) is not int or version != SIDECAR_VERSION:
        raise InvalidGalleryIdentityError(f"Unsupported gallery identity version: {version!r}")

    gallery_id_value = payload["galleryId"]

    if not isinstance(gallery_id_value, str):
        raise InvalidGalleryIdentityError("Gallery identity galleryId must be a string")

    try:
        gallery_id = UUID(gallery_id_value)
    except ValueError as exc:
        raise InvalidGalleryIdentityError("Gallery identity galleryId is not a valid UUID") from exc

    if str(gallery_id) != gallery_id_value:
        raise InvalidGalleryIdentityError(
            "Gallery identity galleryId must use canonical UUID formatting"
        )

    return gallery_id


def read_gallery_id(gallery_directory: str | Path) -> UUID | None:
    gallery_path = Path(gallery_directory).resolve(strict=True)

    if not gallery_path.is_dir():
        raise NotADirectoryError(gallery_path)

    sidecar_path = gallery_path / SIDECAR_FILENAME

    if not os.path.lexists(sidecar_path):
        return None

    if _is_reparse_point(sidecar_path):
        raise InvalidGalleryIdentityError(
            "Gallery identity sidecar cannot be a symbolic link or reparse point"
        )

    if not sidecar_path.is_file():
        raise InvalidGalleryIdentityError("Gallery identity sidecar is not a regular file")

    try:
        content = sidecar_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidGalleryIdentityError("Gallery identity sidecar is not valid UTF-8") from exc

    return _parse_gallery_identity(content)


def _write_temporary_sidecar(
    gallery_path: Path,
    gallery_id: UUID,
) -> Path:
    temporary_path = gallery_path / f".gallery-komganion.{uuid4()}.tmp"

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL

    descriptor = os.open(temporary_path, flags, 0o600)

    payload = {
        "version": SIDECAR_VERSION,
        "galleryId": str(gallery_id),
    }

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            json.dump(payload, file, separators=(",", ":"))
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    return temporary_path


def get_or_create_gallery_id(
    gallery_directory: str | Path,
) -> UUID:
    gallery_path = Path(gallery_directory).resolve(strict=True)

    if not gallery_path.is_dir():
        raise NotADirectoryError(gallery_path)

    existing_id = read_gallery_id(gallery_path)

    if existing_id is not None:
        return existing_id

    new_id = uuid4()
    temporary_path = _write_temporary_sidecar(
        gallery_path,
        new_id,
    )
    sidecar_path = gallery_path / SIDECAR_FILENAME

    try:
        # Creating a hard link is atomic and refuses to replace an existing
        # destination. This protects against simultaneous scanner workers.
        os.link(temporary_path, sidecar_path)
    except FileExistsError:
        existing_id = read_gallery_id(gallery_path)

        if existing_id is None:
            raise RuntimeError("Gallery identity sidecar appeared but could not be read")

        return existing_id
    finally:
        temporary_path.unlink(missing_ok=True)

    _mark_hidden_on_windows(sidecar_path)
    return new_id
