"""Administração: papéis do app, configurações, catalogs, inventário e trilha de auditoria."""

from __future__ import annotations

import json
import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server import db, engine, executor, rules
from server.config import INVENTORY_JOB_ID, get_workspace_client, sql
from server.rbac import UserCtx, require_admin, require_view

router = APIRouter(prefix="/api/admin")

EDITABLE_SETTINGS = {"group_prefix", "group_scope_filter", "sensitivity_tag_key", "demo_mode", "allow_self_approval",
                     "clone_group_pattern", "system_groups", "floor_privileges", "app_principals",
                     "audit_lookback_days"}


class RoleIn(BaseModel):
    principal: str = Field(..., min_length=3)
    principal_type: str = Field("user", pattern="^(user|group)$")
    role: str = Field(..., pattern="^(admin|steward|dpo|auditor)$")
    domain: str | None = None


class CatalogIn(BaseModel):
    physical_name: str
    managed: bool = True


@router.get("/roles")
def roles(user: UserCtx = Depends(require_view)):
    return db.query("SELECT * FROM app_roles ORDER BY role, domain NULLS FIRST, principal")


@router.post("/roles")
def add_role(body: RoleIn, user: UserCtx = Depends(require_admin)):
    if body.role == "steward" and not body.domain:
        raise HTTPException(400, "steward precisa de domínio")
    row = db.execute("""INSERT INTO app_roles (principal, principal_type, role, domain, granted_by)
                        VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING *""",
                     (body.principal, body.principal_type, body.role, body.domain if body.role == "steward" else None,
                      user.email))
    executor.log(user.email, "role_add", body.principal, body.model_dump())
    return row or {"ok": True}


@router.delete("/roles/{role_id}")
def remove_role(role_id: int, user: UserCtx = Depends(require_admin)):
    row = db.query_one("SELECT * FROM app_roles WHERE id = %s", (role_id,))
    if not row:
        raise HTTPException(404, "papel não encontrado")
    if row["role"] == "admin" and db.query_one("SELECT count(*) AS n FROM app_roles WHERE role = 'admin'")["n"] <= 1:
        raise HTTPException(400, "não é possível remover o último admin")
    db.execute("DELETE FROM app_roles WHERE id = %s", (role_id,))
    executor.log(user.email, "role_remove", row["principal"], {"role": row["role"], "domain": row["domain"]})
    return {"deleted": role_id}


@router.get("/settings")
def get_settings(user: UserCtx = Depends(require_view)):
    return {r["key"]: r["value"] for r in db.query("SELECT key, value FROM settings ORDER BY key")}


@router.put("/settings/{key}")
def put_setting(key: str, value: dict, user: UserCtx = Depends(require_admin)):
    if key not in EDITABLE_SETTINGS:
        raise HTTPException(400, "configuração não editável")
    db.execute("""INSERT INTO settings (key, value, updated_by) VALUES (%s,%s,%s)
                  ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by,
                    updated_at = now()""", (key, json.dumps(value.get("value")), user.email))
    executor.log(user.email, "setting", key, value)
    engine.invalidate()
    return {"ok": True}


@router.get("/catalogs")
def catalogs(user: UserCtx = Depends(require_view)):
    return db.query("SELECT * FROM catalogs ORDER BY sort_order")


@router.put("/catalogs/{logical}")
def put_catalog(logical: str, body: CatalogIn, user: UserCtx = Depends(require_admin)):
    row = db.execute("UPDATE catalogs SET physical_name = %s, managed = %s WHERE logical_name = %s RETURNING *",
                     (body.physical_name, body.managed, logical))
    if not row:
        raise HTTPException(404, "catalog lógico não encontrado")
    executor.log(user.email, "catalog_map", logical, body.model_dump())
    engine.invalidate()
    return row


_running = threading.Event()


def _inline_inventory(actor: str) -> None:
    from server import inventory
    try:
        with db.connection() as conn:
            inventory.run_inventory(get_workspace_client(), sql(), conn)
        engine.invalidate()
        rules.evaluate()
        executor.log(actor, "inventory_inline", None, {"ok": True})
    except Exception as ex:  # noqa: BLE001
        db.execute("UPDATE inv_state SET status = 'error', error = %s WHERE id = 1", (str(ex)[:2000],))
    finally:
        _running.clear()


@router.get("/inventory")
def inventory_state(user: UserCtx = Depends(require_view)):
    st = db.query_one("SELECT * FROM inv_state WHERE id = 1")
    run = None
    if INVENTORY_JOB_ID:
        try:
            runs = list(get_workspace_client().jobs.list_runs(job_id=int(INVENTORY_JOB_ID), limit=1))
            if runs:
                r = runs[0]
                run = {"run_id": r.run_id, "state": r.state.life_cycle_state.value if r.state and r.state.life_cycle_state else None,
                       "result": r.state.result_state.value if r.state and r.state.result_state else None,
                       "url": r.run_page_url}
        except Exception:  # noqa: BLE001
            run = None
    return {"state": st, "job_id": INVENTORY_JOB_ID or None, "last_run": run, "inline_running": _running.is_set()}


@router.post("/inventory/run")
def run_inventory(user: UserCtx = Depends(require_admin)):
    executor.log(user.email, "inventory_run", None, {"job_id": INVENTORY_JOB_ID})
    if INVENTORY_JOB_ID:
        r = get_workspace_client().jobs.run_now(job_id=int(INVENTORY_JOB_ID))
        return {"mode": "job", "run_id": r.run_id}
    if _running.is_set():
        return {"mode": "inline", "running": True}
    _running.set()
    threading.Thread(target=_inline_inventory, args=(user.email,), daemon=True).start()
    return {"mode": "inline", "started": True}


@router.post("/rules/evaluate")
def evaluate(user: UserCtx = Depends(require_admin)):
    engine.invalidate()
    return {"open": rules.evaluate()}


@router.get("/log")
def action_log(limit: int = 200, user: UserCtx = Depends(require_view)):
    return db.query("SELECT * FROM action_log ORDER BY at DESC LIMIT %s", (min(limit, 1000),))
