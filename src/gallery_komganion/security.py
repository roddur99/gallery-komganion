from __future__ import annotations

import os
import secrets
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from gallery_komganion.config import load_config

API_TOKEN_ENVIRONMENT_VARIABLE = "GALLERY_KOMGANION_API_TOKEN"

bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def get_api_token() -> str:
    token = os.environ.get(API_TOKEN_ENVIRONMENT_VARIABLE)

    if token is None:
        configured_token = load_config().security.api_token
        token = configured_token.get_secret_value() if configured_token is not None else None

    if token is None:
        raise RuntimeError(
            f"{API_TOKEN_ENVIRONMENT_VARIABLE} or security.api_token must be configured"
        )

    if len(token) < 32:
        raise RuntimeError(f"{API_TOKEN_ENVIRONMENT_VARIABLE} must contain at least 32 characters")

    return token


def require_api_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    expected_token: Annotated[str, Depends(get_api_token)],
) -> None:
    authenticated = (
        credentials is not None
        and credentials.scheme.casefold() == "bearer"
        and secrets.compare_digest(
            credentials.credentials,
            expected_token,
        )
    )

    if not authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token",
            headers={"WWW-Authenticate": "Bearer"},
        )
