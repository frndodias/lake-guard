"""Alertas de violação + ciclo de vida e remediação."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from server import db
from server.auth import current_user
from server.config import get_app_workspace_id, get_workspace_client

router = APIRouter(prefix="/api")

_VALID_STATUS = ("open", "investigating", "resolved", "false_positive")


class StatusPatch(BaseModel):
    status: str
    notes: str | None = None


def _where(**filters) -> tuple[str, list]:
    """Monta o WHERE a partir dos filtros preenchidos (colunas de `alerts a`)."""
    where, params = [], []
    for col, val in filters.items():
        if not val:
            continue
        if col == "principal":
            where.append("lower(a.principal) = lower(%s)")
        else:
            where.append(f"a.{col} = %s")
        params.append(val)
    return (f"WHERE {' AND '.join(where)}" if where else ""), params


@router.get("/alerts")
async def list_alerts(
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    principal: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
):
    clause, params = _where(status=status, severity=severity, principal=principal,
                            workspace_id=workspace_id)
    total = db.query_one(f"SELECT COUNT(*) AS n FROM alerts a {clause}", tuple(params))["n"]
    items = db.query(
        f"""
        SELECT a.id, a.principal, a.capability, a.asset_type, a.asset_id, a.asset_name,
               a.service_name, a.action_name, a.workspace_id, w.workspace_name, w.workspace_url,
               a.source_ip, a.event_time, a.severity, a.status, a.detected_at,
               a.resolved_by, a.resolved_at, a.notes
        FROM alerts a LEFT JOIN workspaces w ON w.workspace_id = a.workspace_id
        {clause}
        ORDER BY a.event_time DESC NULLS LAST, a.detected_at DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, offset]),
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/alerts/stats")
async def alert_stats(workspace_id: str | None = Query(default=None)):
    clause, params = _where(workspace_id=workspace_id)
    p = tuple(params)
    open_clause = f"{clause} {'AND' if clause else 'WHERE'} a.status IN ('open','investigating')"
    by_status = db.query(f"SELECT status, COUNT(*) AS n FROM alerts a {clause} GROUP BY status", p)
    by_severity = db.query(f"SELECT severity, COUNT(*) AS n FROM alerts a {clause} GROUP BY severity", p)
    by_capability = db.query(
        f"SELECT capability, COUNT(*) AS n FROM alerts a {clause} GROUP BY capability ORDER BY n DESC", p
    )
    top_offenders = db.query(
        f"""
        SELECT principal, COUNT(*) AS n
        FROM alerts a {open_clause}
        GROUP BY principal ORDER BY n DESC LIMIT 10
        """,
        p,
    )
    by_workspace = db.query(
        f"""
        SELECT a.workspace_id, w.workspace_name, COUNT(*) AS n
        FROM alerts a LEFT JOIN workspaces w ON w.workspace_id = a.workspace_id
        {open_clause}
        GROUP BY a.workspace_id, w.workspace_name ORDER BY n DESC LIMIT 10
        """,
        p,
    )
    return {
        "by_status": by_status,
        "by_severity": by_severity,
        "by_capability": by_capability,
        "top_offenders": top_offenders,
        "by_workspace": by_workspace,
    }


@router.get("/alerts/{alert_id}")
async def get_alert(alert_id: int):
    alert = db.query_one("SELECT * FROM alerts WHERE id = %s", (alert_id,))
    if not alert:
        raise HTTPException(status_code=404, detail="alerta não encontrado")
    alert["actions"] = db.query(
        "SELECT * FROM alert_actions WHERE alert_id = %s ORDER BY performed_at", (alert_id,)
    )
    return alert


@router.patch("/alerts/{alert_id}")
async def patch_status(alert_id: int, patch: StatusPatch, request: Request):
    if patch.status not in _VALID_STATUS:
        raise HTTPException(status_code=400, detail="status inválido")
    actor = current_user(request).email or "system"
    resolved = patch.status in ("resolved", "false_positive")
    row = db.execute(
        """
        UPDATE alerts
        SET status = %s,
            notes = COALESCE(%s, notes),
            resolved_by = CASE WHEN %s THEN %s ELSE resolved_by END,
            resolved_at = CASE WHEN %s THEN now() ELSE resolved_at END
        WHERE id = %s
        RETURNING *
        """,
        (patch.status, patch.notes, resolved, actor, resolved, alert_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail="alerta não encontrado")
    db.execute(
        "INSERT INTO alert_actions (alert_id, action, performed_by, detail) VALUES (%s,'status_change',%s,%s)",
        (alert_id, actor, f"status -> {patch.status}"),
    )
    return row


# Mapeia capability -> ação de deleção no SDK (remediação real, best-effort)
_DELETERS = {
    "job": lambda w, aid: w.jobs.delete(job_id=int(aid)),
    "dashboard": lambda w, aid: w.lakeview.trash(dashboard_id=aid),
    "warehouse": lambda w, aid: w.warehouses.delete(id=aid),
    "pipeline": lambda w, aid: w.pipelines.delete(pipeline_id=aid),
    "model_serving": lambda w, aid: w.serving_endpoints.delete(name=aid),
}


@router.post("/alerts/{alert_id}/remediate")
async def remediate(alert_id: int, request: Request):
    """Remediação: tenta deletar o asset não-autorizado e resolve o alerta."""
    actor = current_user(request).email or "system"
    alert = db.query_one("SELECT * FROM alerts WHERE id = %s", (alert_id,))
    if not alert:
        raise HTTPException(status_code=404, detail="alerta não encontrado")

    # A app só tem credencial no próprio workspace — não remedia assets de outros.
    if str(alert.get("workspace_id")) != get_app_workspace_id():
        raise HTTPException(
            status_code=422,
            detail="remediação automática só no workspace da app; resolva este alerta no workspace de origem",
        )
    deleter = _DELETERS.get(alert["capability"])
    if not deleter or not alert.get("asset_id"):
        raise HTTPException(
            status_code=422,
            detail=f"remediação automática indisponível para '{alert['capability']}'",
        )
    try:
        deleter(get_workspace_client(), alert["asset_id"])
        detail = f"asset {alert['asset_id']} deletado"
        ok = True
    except Exception as e:  # noqa: BLE001
        detail = f"falha ao deletar: {e}"
        ok = False

    db.execute(
        "INSERT INTO alert_actions (alert_id, action, performed_by, detail) VALUES (%s,'deleted',%s,%s)",
        (alert_id, actor, detail),
    )
    if ok:
        db.execute(
            "UPDATE alerts SET status='resolved', resolved_by=%s, resolved_at=now() WHERE id=%s",
            (actor, alert_id),
        )
    return {"ok": ok, "detail": detail}
