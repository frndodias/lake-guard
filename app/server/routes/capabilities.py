"""Catálogo de capacidades governáveis."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server import db

router = APIRouter(prefix="/api")


class CapabilityPatch(BaseModel):
    enabled: bool | None = None
    default_severity: str | None = None


@router.get("/capabilities")
async def list_capabilities():
    return db.query(
        """
        SELECT c.code, c.label, c.description, c.audit_service, c.audit_actions,
               c.default_severity, c.enabled,
               (SELECT COUNT(*) FROM grants g WHERE g.capability = c.code AND g.allowed) AS grant_count
        FROM capabilities c
        ORDER BY c.label
        """
    )


@router.patch("/capabilities/{code}")
async def patch_capability(code: str, patch: CapabilityPatch):
    if patch.default_severity and patch.default_severity not in ("info", "warning", "critical"):
        raise HTTPException(status_code=400, detail="severity inválida")
    sets, params = [], []
    if patch.enabled is not None:
        sets.append("enabled = %s")
        params.append(patch.enabled)
    if patch.default_severity is not None:
        sets.append("default_severity = %s")
        params.append(patch.default_severity)
    if not sets:
        raise HTTPException(status_code=400, detail="nada para atualizar")
    params.append(code)
    row = db.execute(
        f"UPDATE capabilities SET {', '.join(sets)} WHERE code = %s RETURNING *", tuple(params)
    )
    if not row:
        raise HTTPException(status_code=404, detail="capability não encontrada")
    return row
