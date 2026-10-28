"""Lakeguard — Governança de acessos no Databricks (modelo de personas).

FastAPI: expõe a API e serve o SPA React (frontend/dist).
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server import db
from server.routes.admin import router as admin_router
from server.routes.alerts import router as alerts_router
from server.routes.domains import router as domains_router
from server.routes.explore import router as explore_router
from server.routes.me import router as me_router
from server.routes.migration import router as migration_router
from server.routes.overview import router as overview_router
from server.routes.personas import router as personas_router
from server.routes.requests import router as requests_router

log = logging.getLogger("lakeguard")

app = FastAPI(
    title="Lakeguard",
    description="Governança de acessos no Databricks: visão 360, personas, solicitações e migração",
    version="2.0.0",
)

for r in (me_router, overview_router, explore_router, personas_router, domains_router, requests_router,
          migration_router, alerts_router, admin_router):
    app.include_router(r)


@app.on_event("startup")
def ensure_model() -> None:
    """Primeiro start: carrega o modelo de personas do documento (se vazio)."""
    try:
        if not db.query_one("SELECT 1 AS ok FROM personas LIMIT 1"):
            from server.seed import seed_model
            with db.connection() as conn:
                seed_model(conn)
            log.info("modelo de personas carregado")
    except Exception as ex:  # noqa: BLE001
        log.warning("não foi possível verificar o modelo: %s", ex)


@app.get("/api/health")
def health():
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
