from fastapi import Depends, FastAPI

from gallery_komganion.api.galleries import (
    router as galleries_router,
)
from gallery_komganion.security import require_api_token

app = FastAPI(
    title="Gallery Komganion",
    version="0.1.0",
)

app.include_router(
    galleries_router,
    prefix="/api/v1",
    dependencies=[Depends(require_api_token)],
)


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
