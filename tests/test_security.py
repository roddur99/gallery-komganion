from pathlib import Path

import pytest

from gallery_komganion.config import CONFIG_PATH_ENVIRONMENT_VARIABLE
from gallery_komganion.security import (
    API_TOKEN_ENVIRONMENT_VARIABLE,
    get_api_token,
)


def test_configured_api_token_is_used_when_environment_is_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "configured-token-that-is-at-least-32-characters"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
[security]
api_token = "{token}"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv(CONFIG_PATH_ENVIRONMENT_VARIABLE, str(config_path))
    monkeypatch.delenv(API_TOKEN_ENVIRONMENT_VARIABLE, raising=False)
    get_api_token.cache_clear()

    try:
        assert get_api_token() == token
    finally:
        get_api_token.cache_clear()


def test_environment_api_token_overrides_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[security]
api_token = "configured-token-that-is-at-least-32-characters"
""".strip(),
        encoding="utf-8",
    )
    environment_token = "environment-token-that-is-at-least-32-characters"
    monkeypatch.setenv(CONFIG_PATH_ENVIRONMENT_VARIABLE, str(config_path))
    monkeypatch.setenv(API_TOKEN_ENVIRONMENT_VARIABLE, environment_token)
    get_api_token.cache_clear()

    try:
        assert get_api_token() == environment_token
    finally:
        get_api_token.cache_clear()
