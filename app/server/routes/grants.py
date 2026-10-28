"""Concessões de permissão (cadastro de roles por usuário/grupo)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from server import db
from server.auth import current_user
from server.services import effective_permissions, user_groups

router = APIRouter(prefix="/api")


class GrantIn(BaseModel):
    principal: str = Field(..., min_length=1)
    principal_type: str = Field(default="user")
    capability: str = Field(..., min_length=1)
    workspace_id: str = Field(default="*", min_length=1)  # '*' = account inteira
    allowed: bool = True


@router.get("/grants")
async def list_grants(principal: str | None = None, workspace_id: str | None = None):
    where, params = [], []
    if principal:
        where.append("lower(principal) = lower(%s)")
        params.append(principal)
    if workspace_id:
        where.append("workspace_id = %s")
        params.append(workspace_id)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    return db.query(
        f"SELECT * FROM grants {clause} ORDER BY principal, capability, workspace_id",
        tuple(params),
    )


@router.post("/grants")
async def upsert_grant(grant: GrantIn, request: Request):
    if grant.principal_type not in ("user", "group"):
        raise HTTPException(status_code=400, detail="principal_type inválido")
    actor = current_user(request).email or "system"
    row = db.execute(
        """
        INSERT INTO grants (principal, principal_type, capability, workspace_id, allowed, granted_by)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (principal, capability, workspace_id)
        DO UPDATE SET allowed = EXCLUDED.allowed,
                      principal_type = EXCLUDED.principal_type,
                      granted_by = EXCLUDED.granted_by,
                      granted_at = now()
        RETURNING *
        """,
        (grant.principal, grant.principal_type, grant.capability, grant.workspace_id,
         grant.allowed, actor),
    )
    return row


@router.delete("/grants/{grant_id}")
async def delete_grant(grant_id: int):
    row = db.execute("DELETE FROM grants WHERE id = %s RETURNING id", (grant_id,))
    if not row:
        raise HTTPException(status_code=404, detail="grant não encontrado")
    return {"deleted": grant_id}


@router.get("/grants/effective/{email}")
async def get_effective(email: str, workspace_id: str | None = None):
    """Permissão efetiva resolvida (user + grupos) num workspace — para a UI de auditoria.
    Sem workspace_id, mostra só o que vale para a account inteira."""
    groups = user_groups(email)
    perms = effective_permissions(email, groups, workspace_id)
    return {"email": email, "groups": groups, "workspace_id": workspace_id,
            "permissions": list(perms.values())}
