"""Workspaces da account (para o filtro da UI)."""

from __future__ import annotations

from fastapi import APIRouter

from server import db
from server.config import get_app_workspace_id

router = APIRouter(prefix="/api")


@router.get("/workspaces")
async def list_workspaces():
    """Workspaces com alertas + o da app, com nome (quando conhecido) e nº de abertos."""
    app_ws = get_app_workspace_id()
    rows = db.query(
        """
        SELECT ids.workspace_id, w.workspace_name, w.workspace_url,
               COALESCE(c.n_open, 0) AS n_open
        FROM (
            SELECT DISTINCT workspace_id FROM alerts WHERE workspace_id IS NOT NULL
            UNION SELECT %s
        ) ids
        LEFT JOIN workspaces w ON w.workspace_id = ids.workspace_id
        LEFT JOIN (
            SELECT workspace_id, COUNT(*) AS n_open
            FROM alerts WHERE status IN ('open','investigating')
            GROUP BY workspace_id
        ) c ON c.workspace_id = ids.workspace_id
        ORDER BY n_open DESC, w.workspace_name NULLS LAST, ids.workspace_id
        """,
        (app_ws,),
    )
    for r in rows:
        r["is_app_workspace"] = r["workspace_id"] == app_ws
    return {"app_workspace_id": app_ws, "workspaces": rows}
