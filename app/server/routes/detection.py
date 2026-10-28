"""Controle do motor de detecção (status + disparo sob demanda)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from server import db
from server.config import DETECTION_JOB_ID, get_workspace_client

router = APIRouter(prefix="/api")


@router.get("/detection/status")
async def status():
    """Estado da última execução (checkpoint) + se o disparo está habilitado."""
    st = db.query_one(
        "SELECT last_event_time, last_run_at, last_run_status, last_error FROM detection_state WHERE id = 1"
    )
    return {"job_configured": bool(DETECTION_JOB_ID), "state": st}


@router.post("/detection/run")
async def run():
    """Dispara o job de detecção sob demanda (run-now)."""
    if not DETECTION_JOB_ID:
        raise HTTPException(status_code=503, detail="DETECTION_JOB_ID não configurado no app.yaml")
    w = get_workspace_client()
    try:
        resp = w.jobs.run_now(job_id=int(DETECTION_JOB_ID))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Falha ao disparar detecção: {e}") from e
    return {"run_id": resp.run_id}


@router.get("/detection/run/{run_id}")
async def run_state(run_id: int):
    """Estado de uma execução específica (para acompanhar o disparo)."""
    w = get_workspace_client()
    try:
        r = w.jobs.get_run(run_id=run_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(e)) from e
    s = r.state
    return {
        "run_id": run_id,
        "life_cycle_state": s.life_cycle_state.value if s and s.life_cycle_state else None,
        "result_state": s.result_state.value if s and s.result_state else None,
    }
