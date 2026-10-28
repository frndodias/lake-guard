"""Migração: de-para dos grupos legados, ondas com prévia de impacto e rollback."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server import db, engine, executor, migration, workflow
from server.rbac import UserCtx, require_admin, require_view

router = APIRouter(prefix="/api/migration")

ACTIONS = ["to_persona", "to_clearance", "delete", "to_sp", "shrink_to_floor", "keep"]


class MappingIn(BaseModel):
    action: str
    target: str | None = None


class WaveIn(BaseModel):
    name: str = Field(..., min_length=2)
    groups: list[str] = Field(..., min_length=1)


@router.get("/groups")
def groups(user: UserCtx = Depends(require_view)):
    s = engine.snapshot()
    return {"groups": migration.sync_mappings(s, user.email), "actions": ACTIONS,
            "personas": list(s.personas.keys()),
            "domains": [d["code"] for d in s.domains.values() if d.get("clearance_group")]}


@router.put("/mappings/{group}")
def set_mapping(group: str, body: MappingIn, user: UserCtx = Depends(require_admin)):
    if body.action not in ACTIONS:
        raise HTTPException(400, "ação inválida")
    return db.execute("""INSERT INTO migration_mappings (legacy_group, action, target, suggested, updated_by)
                         VALUES (%s,%s,%s,FALSE,%s)
                         ON CONFLICT (legacy_group) DO UPDATE SET action = EXCLUDED.action, target = EXCLUDED.target,
                           suggested = FALSE, updated_by = EXCLUDED.updated_by, updated_at = now()
                         RETURNING *""", (group, body.action, body.target, user.email))


@router.get("/waves")
def waves(user: UserCtx = Depends(require_view)):
    return db.query("SELECT w.*, cr.status AS request_status FROM migration_waves w "
                    "LEFT JOIN change_requests cr ON cr.id = w.change_id ORDER BY wave_order, id")


@router.post("/waves")
def create_wave(body: WaveIn, user: UserCtx = Depends(require_admin)):
    n = db.query_one("SELECT COALESCE(MAX(wave_order), 0) + 1 AS n FROM migration_waves")["n"]
    return db.execute("INSERT INTO migration_waves (name, wave_order, groups, created_by) VALUES (%s,%s,%s,%s) "
                      "RETURNING *", (body.name, n, body.groups, user.email))


@router.delete("/waves/{wave_id}")
def delete_wave(wave_id: int, user: UserCtx = Depends(require_admin)):
    w = db.query_one("SELECT status FROM migration_waves WHERE id = %s", (wave_id,))
    if not w or w["status"] not in ("draft", "rolled_back"):
        raise HTTPException(400, "só ondas em rascunho podem ser removidas")
    db.execute("DELETE FROM migration_waves WHERE id = %s", (wave_id,))
    return {"deleted": wave_id}


def _wave(wave_id: int) -> dict:
    w = db.query_one("SELECT * FROM migration_waves WHERE id = %s", (wave_id,))
    if not w:
        raise HTTPException(404, "onda não encontrada")
    return w


@router.get("/waves/{wave_id}/preview")
def preview(wave_id: int, user: UserCtx = Depends(require_view)):
    w = _wave(wave_id)
    s = engine.snapshot()
    ops, inverse, notes = migration.wave_plan(s, list(w["groups"]))
    return {"wave": w, "plan": ops, "inverse": inverse, "notes": notes, "impact": s.impact(ops),
            "script": executor.script(ops)}


@router.post("/waves/{wave_id}/submit")
def submit(wave_id: int, user: UserCtx = Depends(require_admin)):
    w = _wave(wave_id)
    if w["status"] not in ("draft", "rolled_back"):
        raise HTTPException(400, "onda já enviada")
    s = engine.snapshot()
    ops, inverse, notes = migration.wave_plan(s, list(w["groups"]))
    if not ops:
        raise HTTPException(400, "onda sem operações: " + "; ".join(notes))
    req = workflow.create("migration_wave", f"Onda {w['wave_order']}: {w['name']} ({len(ops)} operações)",
                          user.email, ops, payload={"wave_id": wave_id, "groups": list(w["groups"]), "notes": notes},
                          target=f"wave:{wave_id}", impact=s.impact(ops))
    db.execute("UPDATE migration_waves SET status = 'pending', change_id = %s, snapshot = %s WHERE id = %s",
               (req["id"], json.dumps({"inverse": inverse}), wave_id))
    return req


@router.post("/waves/{wave_id}/rollback")
def rollback(wave_id: int, user: UserCtx = Depends(require_admin)):
    w = _wave(wave_id)
    if w["status"] != "executed":
        raise HTTPException(400, "só ondas executadas podem ser revertidas")
    inverse = (w["snapshot"] or {}).get("inverse") or []
    s = engine.snapshot()
    return workflow.create("migration_rollback", f"Rollback da onda {w['wave_order']}: {w['name']}", user.email,
                           inverse, payload={"wave_id": wave_id, "groups": list(w["groups"])},
                           target=f"wave:{wave_id}", impact=s.impact(inverse))
