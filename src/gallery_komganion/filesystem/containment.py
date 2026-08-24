from __future__ import annotations

import os
import stat
from pathlib import Path, PureWindowsPath


class UnsafePathError(ValueError):
    """Raised when a path could escape an approved filesystem root."""


def canonicalize_approved_root(root: str | Path) -> Path:
    resolved_root = Path(root).expanduser().resolve(strict=True)

    if not resolved_root.is_dir():
        raise NotADirectoryError(f"Approved gallery root is not a directory: {resolved_root}")

    return resolved_root


def _validate_stored_relative_path(stored_relative_path: str | Path) -> str:
    value = os.fspath(stored_relative_path)

    if not value:
        raise UnsafePathError("Stored relative path cannot be empty")

    if "\x00" in value:
        raise UnsafePathError("Stored relative path contains a null byte")

    # Database paths use forward slashes on every platform. This keeps the API
    # representation consistent and prevents ambiguous Windows path handling.
    if "\\" in value:
        raise UnsafePathError("Stored relative paths must use forward slashes")

    if ":" in value:
        raise UnsafePathError("Stored relative path cannot contain a colon")

    platform_path = Path(value)
    windows_path = PureWindowsPath(value)

    if platform_path.is_absolute() or windows_path.is_absolute():
        raise UnsafePathError("Absolute paths are not allowed")

    if windows_path.drive or windows_path.root:
        raise UnsafePathError("Drive-qualified paths are not allowed")

    if ".." in platform_path.parts or ".." in windows_path.parts:
        raise UnsafePathError("Parent-directory traversal is not allowed")

    return value


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False

    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    file_attributes = getattr(metadata, "st_file_attributes", 0)

    return path.is_symlink() or bool(file_attributes & reparse_flag)


def _reject_reparse_descendants(
    resolved_root: Path,
    relative_path: Path,
) -> None:
    current = resolved_root

    for part in relative_path.parts:
        if part == ".":
            continue

        current = current / part

        # lexists also detects broken symbolic links.
        if os.path.lexists(current) and _is_reparse_point(current):
            raise UnsafePathError(f"Symbolic links and reparse points are not allowed: {current}")


def _verify_containment(
    resolved_root: Path,
    resolved_candidate: Path,
) -> None:
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise UnsafePathError("Resolved path is outside the approved gallery root") from exc


def safe_join(
    root: str | Path,
    stored_relative_path: str | Path,
    *,
    must_exist: bool = True,
) -> Path:
    """Resolve a stored relative path beneath an approved root.

    This function must only receive relative paths previously stored by the
    server. API clients should provide gallery or page IDs, never paths.
    """

    resolved_root = canonicalize_approved_root(root)
    validated_path = _validate_stored_relative_path(stored_relative_path)
    relative_path = Path(validated_path)

    _reject_reparse_descendants(resolved_root, relative_path)

    candidate = resolved_root / relative_path
    resolved_candidate = candidate.resolve(strict=must_exist)

    _verify_containment(resolved_root, resolved_candidate)

    if must_exist and not resolved_candidate.exists():
        raise FileNotFoundError(resolved_candidate)

    return resolved_candidate


def stored_relative_path(
    root: str | Path,
    candidate: str | Path,
) -> str:
    """Convert a server-discovered path into a portable stored path."""

    resolved_root = canonicalize_approved_root(root)
    resolved_candidate = Path(candidate).expanduser().resolve(strict=True)

    _verify_containment(resolved_root, resolved_candidate)

    relative_path = resolved_candidate.relative_to(resolved_root)

    _reject_reparse_descendants(resolved_root, relative_path)

    if relative_path == Path("."):
        return "."

    return relative_path.as_posix()
