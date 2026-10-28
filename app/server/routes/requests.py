"""Solicitações: pedir acesso (clearance/persona), aprovar, rejeitar, revogar, expirar."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server import db, engine, workflow
from server import identity as idn
from server.config import get_workspace_client
from server.rbac import UserCtx, get_user, require_admin

router = APIRouter(prefix="/api")


class AccessIn(BaseModel):
    target_type: str = Field(..., pattern="^(clearance|persona)$")
    target: str
    member_id: str | None = None          # vazio = eu mesmo
    duration_days: int = Field(30, ge=1, le=365)
    justification: str = Field(..., min_length=5)


class Decision(BaseModel):
    note: str | None = None


def _decorate(rows: list[dict], user: UserCtx) -> list[dict]:
    for r in rows:
        r["can_approve"] = workflow.stages_for(user, r)
        r["is_mine"] = r["requested_by"].lower() == user.email.lower()
    return rows


@router.get("/requests")
def list_requests(scope: str = "mine", status: str | None = None, user: UserCtx = Depends(get_user)):
    where, params = [], []
    if status:
        where.append("status = %s")
        params.append(status)
    if scope == "mine" or not user.can_view:
        where.append("lower(requested_by) = lower(%s)")
        params.append(user.email)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = db.query(f"SELECT * FROM change_requests {clause} ORDER BY created_at DESC LIMIT 300", tuple(params))
    rows = _decorate(rows, user)
    if scope == "to_approve":
        rows = [r for r in rows if r["can_approve"]]
    return rows


@router.get("/requests/targets")
def targets(user: UserCtx = Depends(get_user)):
    s = engine.snapshot()
    return {
        "clearance": [{"code": d["code"], "name": d["name"], "sensitivity": d["sensitivity"],
                       "group": s.phys_group(d["clearance_group"]), "requires_dpo": d["sensitivity"] == "critical",
                       "exists": bool(s.pid(s.phys_group(d["clearance_group"])))}
                      for d in s.domains.values() if d.get("clearance_group")],
        "personas": [{"code": c, "label": p["label"], "group": s.phys_group(p["group_name"])}
                     for c, p in s.personas.items()],
        "people": sorted([{"id": pid, "label": s.label(pid), "type": p["type"]} for pid, p in s.principals.items()
                          if p["type"] in ("user", "sp")], key=lambda x: x["label"]),
        "me": s.pid(user.email),
    }


@router.get("/requests/{req_id}")
def get_request(req_id: int, user: UserCtx = Depends(get_user)):
    r = workflow.get(req_id)
    if not r:
        raise HTTPException(404, "pedido não encontrado")
    if not user.can_view and r["requested_by"].lower() != user.email.lower():
        raise HTTPException(403, "sem acesso a este pedido")
    return _decorate([r], user)[0]


@router.post("/requests/access")
def request_access(body: AccessIn, user: UserCtx = Depends(get_user)):
    s = engine.snapshot()
    member_id = body.member_id
    if member_id and member_id != s.pid(user.email) and not user.is_admin:
        raise HTTPException(403, "só admin pode pedir acesso em nome de outra pessoa")
    if not member_id:
        member_id = s.pid(user.email)
        if not member_id:
            u = idn.find_user(get_workspace_client(), user.email)
            if not u:
                raise HTTPException(400, "seu usuário não foi encontrado na conta")
            member_id = u["id"]
    label = s.label(member_id) if member_id in s.principals else user.email
    mtype = (s.principals.get(member_id) or {}).get("type", "user")
    if body.target_type == "clearance":
        d = s.domains.get(body.target)
        if not d or not d.get("clearance_group"):
            raise HTTPException(400, "domínio sem grupo de clearance")
        gname = s.phys_group(d["clearance_group"])
        domain, requires_dpo, kind = d["code"], d["sensitivity"] == "critical", "access_request"
        title = f"{label}: acesso a dados restritos de {d['name']} por {body.duration_days} dias"
    else:
        p = s.personas.get(body.target)
        if not p:
            raise HTTPException(400, "persona inexistente")
        gname = s.phys_group(p["group_name"])
        domain, requires_dpo, kind = None, False, "membership_add"
        title = f"{label}: entrar na persona {body.target} por {body.duration_days} dias"
    gid = s.pid(gname)
    if not gid:
        raise HTTPException(400, f"grupo {gname} não existe")
    if gid in s.groups_of(member_id):
        raise HTTPException(400, "já faz parte deste grupo")
    plan = [{"op": "add_member", "group": gname, "group_id": gid, "member_id": member_id, "member_name": label,
             "member_type": mtype}]
    impact = s.impact(plan) if member_id in s.principals else None
    return workflow.create(kind, title, user.email, plan, payload={"target_type": body.target_type,
                                                                   "target": body.target, "member_id": member_id},
                           target=body.target, domain=domain, requires_dpo=requires_dpo,
                           duration_days=body.duration_days, justification=body.justification, impact=impact)


def _guard(fn, *args):
    try:
        return fn(*args)
    except PermissionError as ex:
        raise HTTPException(403, str(ex)) from ex
    except ValueError as ex:
        raise HTTPException(400, str(ex)) from ex


@router.post("/requests/{req_id}/approve")
def approve(req_id: int, body: Decision, user: UserCtx = Depends(get_user)):
    return _guard(workflow.approve, req_id, user, body.note)


@router.post("/requests/{req_id}/reject")
def reject(req_id: int, body: Decision, user: UserCtx = Depends(get_user)):
    return _guard(workflow.reject, req_id, user, body.note)


@router.post("/requests/{req_id}/cancel")
def cancel(req_id: int, user: UserCtx = Depends(get_user)):
    return _guard(workflow.cancel, req_id, user)


@router.post("/requests/{req_id}/revoke")
def revoke(req_id: int, user: UserCtx = Depends(get_user)):
    return _guard(workflow.revoke_access, req_id, user)


@router.post("/requests/expire")
def expire(user: UserCtx = Depends(require_admin)):
    return {"expired": workflow.expire_due(actor=user.email)}
