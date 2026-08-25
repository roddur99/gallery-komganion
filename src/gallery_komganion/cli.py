from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from gallery_komganion.config import AppConfig, load_config
from gallery_komganion.database import (
    create_session_factory,
    create_sqlite_engine,
)
from gallery_komganion.services.scanner import (
    discover_galleries,
    synchronize_discovery,
)


def run_scan(config: AppConfig) -> int:
    engine = create_sqlite_engine(config.storage.database_path)
    factory = create_session_factory(engine)
    encountered_error = False

    try:
        enabled_roots = [root for root in config.gallery_roots if root.enabled]

        if not enabled_roots:
            print("No enabled gallery roots are configured.")
            return 0

        for root in enabled_roots:
            print(f"Scanning {root.name}: {root.path}")

            discovery = discover_galleries(root)

            with factory.begin() as session:
                result = synchronize_discovery(
                    session,
                    root,
                    discovery,
                )

            print(
                f"  created={result.created} "
                f"updated={result.updated} "
                f"missing={result.marked_missing} "
                f"pages={result.indexed_pages}"
            )

            errors = [error.message for error in discovery.errors]
            errors.extend(result.errors)

            if not discovery.root_available:
                encountered_error = True
                print("  root unavailable")

            if errors:
                encountered_error = True

                for message in errors:
                    print(f"  error: {message}")
    finally:
        engine.dispose()

    return 1 if encountered_error else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gallery-komganion",
        description="Manage the Gallery Komganion server.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to the configuration TOML file.",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )
    subparsers.add_parser(
        "scan",
        help="Scan configured gallery roots.",
    )

    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parsed = parser.parse_args(arguments)

    try:
        config = load_config(parsed.config)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))

    if parsed.command == "scan":
        return run_scan(config)

    parser.error(f"Unknown command: {parsed.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
