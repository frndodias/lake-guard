"""Lakeguard — Governança e monitoramento de criação de assets no Databricks.

FastAPI: expõe a API e serve o SPA React (frontend/dist).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server import db
from server.routes.alerts import router as alerts_router
from server.routes.assets import router as assets_router
from server.routes.aidk import router as aidk_router
from server.routes.capabilities import router as capabilities_router
from server.routes.chat import router as chat_router
from server.routes.detection import router as detection_router
from server.routes.genie import router as genie_router
from server.routes.grants import router as grants_router
from server.routes.me import router as me_router
from server.routes.users import router as users_router
from server.routes.workspaces import router as workspaces_router

app = FastAPI(
    title="Lakeguard",
    description="Governança e monitoramento de criação de assets no Databricks",
    version="0.1.0",
)

app.include_router(me_router)
app.include_router(users_router)
app.include_router(capabilities_router)
app.include_router(grants_router)
app.include_router(alerts_router)
app.include_router(assets_router)
app.include_router(genie_router)
app.include_router(detection_router)
app.include_router(aidk_router)
app.include_router(chat_router)
app.include_router(workspaces_router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "lakebase": db.healthcheck()}


# ------------------------------------------------------------------ #
# Servir o SPA React
# ------------------------------------------------------------------ #
frontend_dist = Path(__file__).parent / "frontend" / "dist"

if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"error": "Not found"}, status_code=404)
        candidate = frontend_dist / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend_dist / "index.html")
