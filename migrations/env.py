from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from gallery_komganion import models  # noqa: F401
from gallery_komganion.config import load_config
from gallery_komganion.database import Base, sqlite_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

app_config = load_config()

config.set_main_option(
    "sqlalchemy.url",
    sqlite_url(app_config.storage.database_path),
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
