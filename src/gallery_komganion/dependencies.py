from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from gallery_komganion.config import AppConfig, load_config
from gallery_komganion.database import (
    create_session_factory,
    create_sqlite_engine,
)


@lru_cache
def get_config() -> AppConfig:
    return load_config()


@lru_cache
def get_engine() -> Engine:
    config = get_config()
    return create_sqlite_engine(
        config.storage.database_path,
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return create_session_factory(get_engine())


def get_session() -> Generator[Session, None, None]:
    factory = get_session_factory()

    with factory() as session:
        yield session
