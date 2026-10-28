"""Usuário logado + papéis no Lakeguard + flags do ambiente."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from server import db
from server.rbac import UserCtx, get_user

router = APIRouter(prefix="/api")


@router.get("/me")
def me(user: UserCtx = Depends(get_user)):
    flags = {r["key"]: r["value"] for r in db.query(
        "SELECT key, value FROM settings WHERE key IN ('demo_mode', 'allow_self_approval', 'group_prefix')")}
    pending = db.query_one("SELECT count(*) AS n FROM change_requests WHERE status = 'pending'")["n"]
    alerts = db.query_one("SELECT count(*) AS n FROM alerts WHERE status <> 'resolved' AND severity = 'critical'")["n"]
    return {**user.public(), "flags": flags, "badges": {"pending": pending, "critical_alerts": alerts}}
