"""Listagem de usuários (SCIM do workspace + principais da account vistos no audit) e grupos."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from server import db
from server.config import get_workspace_client

router = APIRouter(prefix="/api")


@router.get("/users")
async def list_users(search: str | None = Query(default=None), limit: int = 500):
    """Usuários do workspace da app (SCIM) + principais vistos nos alertas de
    qualquer workspace da account (listar a account toda exigiria account admin)."""
    w = get_workspace_client()
    kwargs: dict = {"count": limit, "attributes": "id,userName,displayName,active,groups"}
    if search:
        kwargs["filter"] = f'userName co "{search}" or displayName co "{search}"'
    try:
        users = list(w.users.list(**kwargs))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Falha SCIM: {e}") from e

    out = [
        {
            "id": u.id,
            "email": u.user_name,
            "name": u.display_name or u.user_name,
            "active": bool(u.active),
            "groups": [g.display for g in (u.groups or []) if g.display],
            "source": "workspace",
            "n_workspaces": None,
        }
        for u in users
    ]

    known = {(u["email"] or "").lower() for u in out}
    audit_principals = db.query(
        """
        SELECT principal, COUNT(DISTINCT workspace_id) AS n_workspaces
        FROM alerts
        WHERE (%s::text IS NULL OR principal ILIKE '%%' || %s::text || '%%')
        GROUP BY principal
        ORDER BY principal
        LIMIT %s
        """,
        (search, search, limit),
    )
    for p in audit_principals:
        if p["principal"].lower() in known:
            continue
        out.append({
            "id": f"audit:{p['principal']}",
            "email": p["principal"],
            "name": p["principal"],
            "active": True,
            "groups": [],
            "source": "account",
            "n_workspaces": p["n_workspaces"],
        })
    return out


@router.get("/groups")
async def list_groups(limit: int = 500):
    w = get_workspace_client()
    try:
        groups = list(w.groups.list(count=limit, attributes="id,displayName,members"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Falha SCIM: {e}") from e
    return [
        {"id": g.id, "name": g.display_name, "members": len(g.members or [])}
        for g in groups
    ]
