from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import uvicorn

from gallery_komganion.config import (
    CONFIG_PATH_ENVIRONMENT_VARIABLE,
    AppConfig,
)
from gallery_komganion.database import (
    Base,
    create_session_factory,
    create_sqlite_engine,
)
from gallery_komganion.services.scanner import (
    discover_galleries,
    synchronize_discovery,
)


@dataclass(frozen=True)
class ScanSummary:
    roots_scanned: int
    created: int
    updated: int
    marked_missing: int
    indexed_pages: int
    errors: tuple[str, ...]


def application_data_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")

    if local_app_data:
        return Path(local_app_data) / "GalleryKomganion"

    return Path.home() / ".gallery-komganion"


def default_config_path() -> Path:
    configured_path = os.environ.get(CONFIG_PATH_ENVIRONMENT_VARIABLE)

    if configured_path:
        return Path(configured_path).expanduser().resolve(strict=False)

    return application_data_directory() / "config.toml"


def ensure_database(config: AppConfig) -> None:
    from gallery_komganion import models  # noqa: F401

    config.storage.database_path.parent.mkdir(parents=True, exist_ok=True)
    config.storage.thumbnail_directory.mkdir(parents=True, exist_ok=True)

    engine = create_sqlite_engine(config.storage.database_path)

    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()


def scan_config(
    config: AppConfig,
    progress: Callable[[str], None] | None = None,
) -> ScanSummary:
    notify = progress or (lambda _message: None)
    ensure_database(config)

    engine = create_sqlite_engine(config.storage.database_path)
    factory = create_session_factory(engine)
    roots_scanned = 0
    created = 0
    updated = 0
    marked_missing = 0
    indexed_pages = 0
    errors: list[str] = []

    try:
        enabled_roots = [root for root in config.gallery_roots if root.enabled]

        for root in enabled_roots:
            roots_scanned += 1
            notify(f"Scanning {root.name}: {root.path}")
            discovery = discover_galleries(root)

            with factory.begin() as session:
                result = synchronize_discovery(
                    session,
                    root,
                    discovery,
                )

            created += result.created
            updated += result.updated
            marked_missing += result.marked_missing
            indexed_pages += result.indexed_pages

            root_errors = [
                f"{root.name}: {error.relative_path}: {error.message}"
                for error in discovery.errors
            ]
            root_errors.extend(f"{root.name}: {message}" for message in result.errors)

            if not discovery.root_available and not root_errors:
                root_errors.append(f"{root.name}: root unavailable")

            errors.extend(root_errors)
            notify(
                f"{root.name}: created={result.created} "
                f"updated={result.updated} missing={result.marked_missing} "
                f"pages={result.indexed_pages}"
            )
    finally:
        engine.dispose()

    return ScanSummary(
        roots_scanned=roots_scanned,
        created=created,
        updated=updated,
        marked_missing=marked_missing,
        indexed_pages=indexed_pages,
        errors=tuple(errors),
    )


def reset_application_dependencies() -> None:
    from gallery_komganion.dependencies import (
        get_config,
        get_engine,
        get_session_factory,
    )
    from gallery_komganion.security import get_api_token

    if get_engine.cache_info().currsize:
        get_engine().dispose()

    get_session_factory.cache_clear()
    get_engine.cache_clear()
    get_config.cache_clear()
    get_api_token.cache_clear()


class ServerController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self, config: AppConfig, config_path: Path) -> None:
        with self._lock:
            if self.running:
                return

            ensure_database(config)
            os.environ[CONFIG_PATH_ENVIRONMENT_VARIABLE] = str(config_path)
            reset_application_dependencies()

            from gallery_komganion.main import app

            uvicorn_config = uvicorn.Config(
                app,
                host=config.server.host,
                port=config.server.port,
                log_level="info",
            )
            server = uvicorn.Server(uvicorn_config)
            server.install_signal_handlers = lambda: None

            thread = threading.Thread(
                target=server.run,
                name="gallery-komganion-server",
                daemon=True,
            )
            self._server = server
            self._thread = thread
            thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        with self._lock:
            server = self._server
            thread = self._thread

            if server is None or thread is None:
                return

            server.should_exit = True

        thread.join(timeout=timeout)

        with self._lock:
            self._server = None
            self._thread = None
