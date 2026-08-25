from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def sqlite_url(database_path: str | Path) -> str:
    path = Path(database_path).expanduser().resolve(strict=False)
    return f"sqlite:///{path.as_posix()}"


def create_sqlite_engine(
    database_path: str | Path,
    *,
    echo: bool = False,
) -> Engine:
    engine = create_engine(
        sqlite_url(database_path),
        echo=echo,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(
        database_connection: sqlite3.Connection,
        _connection_record: object,
    ) -> None:
        cursor = database_connection.cursor()

        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA journal_mode = WAL")
        finally:
            cursor.close()

    return engine


def create_session_factory(
    engine: Engine,
) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


@contextmanager
def session_scope(
    factory: sessionmaker[Session],
) -> Generator[Session, None, None]:
    session = factory()

    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
