"""Área de Personas: configurar permissões e membros, com prévia de impacto e aprovação."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from server import db, engine, executor, workflow
from server.engine import Snapshot
from server.rbac import UserCtx, require_admin, require_view

router = APIRouter(prefix="/api")

VALID_PRIVS = ["USE_CATALOG", "USE_SCHEMA", "BROWSE", "SELECT", "MODIFY", "CREATE_TABLE", "CREATE_SCHEMA",
               "CREATE_FUNCTION", "CREATE_VOLUME", "READ_VOLUME", "EXECUTE", "MANAGE", "ALL_PRIVILEGES"]


class GrantRow(BaseModel):
    catalog: str
    schema_scope: str | None = None
    privileges: list[str]


class PersonaChange(BaseModel):
    grants: list[GrantRow] | None = None
    capabilities: list[str] | None = None
    description: str | None = None
    justification: str | None = None


class MemberIn(BaseModel):
    member_id: str
    justification: str = Field(..., min_length=3)
    duration_days: int | None = None


def _get(s: Snapshot, code: str) -> dict:
    p = s.personas.get(code)
    if not p:
        raise HTTPException(404, "persona não encontrada")
    return p


def _members(s: Snapshot, code: str) -> dict:
    p = s.personas[code]
    gid = s.pid(s.phys_group(p["group_name"]))
    manual = {r["member_id"]: r for r in db.query(
        "SELECT * FROM manual_members WHERE group_name = %s AND removed_at IS NULL", (s.phys_group(p["group_name"]),))}
    direct = []
    for mid in sorted(s.members.get(gid, set()), key=s.label) if gid else []:
        m = s.principals.get(mid) or {"type": "?", "name": mid}
        if m["type"] == "group":
            humans = [x for x in s.transitive_members(mid) if (s.principals.get(x) or {}).get("type") in ("user", "sp")]
            source = "idp" if m.get("group_class") == "idp_persona" else "grupo"
            direct.append({"id": mid, "label": s.label(mid), "type": "group", "source": source,
                           "people": [{"id": h, "label": s.label(h)} for h in sorted(humans, key=s.label)]})
        else:
            mm = manual.get(mid)
            direct.append({"id": mid, "label": s.label(mid), "type": m["type"], "source": "manual" if mm else "direto",
                           "justification": mm["justification"] if mm else None,
                           "expires_at": mm["expires_at"] if mm else None,
                           "approved_by": mm["approved_by"] if mm else None})
    people = [x for x in s.transitive_members(gid) if (s.principals.get(x) or {}).get("type") in ("user", "sp")] if gid else []
    via_idp = sum(len(d["people"]) for d in direct if d["source"] == "idp")
    return {"group": s.phys_group(p["group_name"]), "group_id": gid, "direct": direct, "people": len(people),
            "via_idp": via_idp, "manual": sum(1 for d in direct if d["source"] == "manual"),
            "conflicts": [{"id": x, "label": s.label(x), "personas": s.personas_of(x)} for x in people
                          if len(s.personas_of(x)) > 1]}


@router.get("/personas")
def list_personas(user: UserCtx = Depends(require_view)):
    s = engine.snapshot()
    out = []
    for code, p in s.personas.items():
        gap = s.persona_gap(code)
        mem = _members(s, code)
        out.append({**p, "group": gap["group"], "group_exists": gap["group_exists"], "gap": gap["counts"],
                    "people": mem["people"], "via_idp": mem["via_idp"], "manual": mem["manual"],
                    "conflicts": len(mem["conflicts"]), "capabilities": sorted(s.persona_caps.get(code, set())),
                    "grants": s.persona_grants.get(code, [])})
    return out


@router.get("/personas/meta")
def meta(user: UserCtx = Depends(require_view)):
    s = engine.snapshot()
    caps = db.query("SELECT code, label, severity FROM capabilities ORDER BY label")
    return {"privileges": VALID_PRIVS, "capabilities": caps,
            "catalogs": [{"logical": c["logical_name"], "physical": c["physical_name"], "managed": c["managed"],
                          "env": c["env"], "description": c["description"]} for c in s.catalogs.values()],
            "schema_scopes": ["", "@staging", "@product"]}


@router.get("/personas/{code}")
def persona_detail(code: str, user: UserCtx = Depends(require_view)):
    s = engine.snapshot()
    p = _get(s, code)
    gap = s.persona_gap(code)
    versions = db.query("SELECT version, changed_by, changed_at, change_id FROM persona_versions "
                        "WHERE persona_code = %s ORDER BY version DESC", (code,))
    pending = db.query("SELECT id, kind, title, status, requested_by, created_at FROM change_requests "
                       "WHERE target = %s AND status = 'pending' ORDER BY created_at DESC", (code,))
    return {"persona": p, "grants": s.persona_grants.get(code, []), "expanded": s.expand_persona(code),
            "gap": gap, "plan": s.gap_plan(code), "members": _members(s, code),
            "capabilities": sorted(s.persona_caps.get(code, set())), "versions": versions, "pending": pending}


def _validate(change: PersonaChange, s: Snapshot) -> list[dict] | None:
    if change.grants is None:
        return None
    rows = []
    for g in change.grants:
        if g.catalog not in s.catalogs:
            raise HTTPException(400, f"catalog lógico desconhecido: {g.catalog}")
        bad = [x for x in g.privileges if x not in VALID_PRIVS]
        if bad:
            raise HTTPException(400, f"privilégio inválido: {bad}")
        if g.privileges:
            rows.append({"catalog": g.catalog, "schema_scope": g.schema_scope or None, "privileges": g.privileges})
    return rows


def _preview(s: Snapshot, code: str, change: PersonaChange) -> dict:
    grants = _validate(change, s)
    plan = s.gap_plan(code, grants) if grants is not None else s.gap_plan(code)
    before = {(d["securable"], p) for d in s.expand_persona(code) for p in d["privileges"]}
    after = {(d["securable"], p) for d in s.expand_persona(code, grants) for p in d["privileges"]} if grants is not None else before
    return {"plan": plan, "impact": s.impact(plan), "script": executor.script(plan),
            "desired_added": sorted(after - before), "desired_removed": sorted(before - after)}


@router.post("/personas/{code}/preview")
def preview(code: str, change: PersonaChange, user: UserCtx = Depends(require_view)):
    s = engine.snapshot()
    _get(s, code)
    return _preview(s, code, change)


@router.post("/personas/{code}/propose")
def propose(code: str, change: PersonaChange, user: UserCtx = Depends(require_admin)):
    s = engine.snapshot()
    _get(s, code)
    pv = _preview(s, code, change)
    payload = {"persona": code}
    if change.grants is not None:
        payload["grants"] = _validate(change, s)
    if change.capabilities is not None:
        payload["capabilities"] = change.capabilities
    if change.description is not None:
        payload["description"] = change.description
    return workflow.create("persona_update", f"Alterar persona {code}", user.email, pv["plan"], payload=payload,
                           target=code, justification=change.justification, impact=pv["impact"])


@router.post("/personas/{code}/fix-gap")
def fix_gap(code: str, user: UserCtx = Depends(require_admin)):
    s = engine.snapshot()
    _get(s, code)
    plan = s.gap_plan(code)
    if not plan:
        raise HTTPException(400, "persona já está conforme o modelo")
    return workflow.create("gap_fix", f"Alinhar persona {code} ao modelo ({len(plan)} operações)", user.email, plan,
                           payload={"persona": code}, target=code, impact=s.impact(plan))


@router.get("/personas/{code}/script", response_class=PlainTextResponse)
def gap_script(code: str, user: UserCtx = Depends(require_view)):
    s = engine.snapshot()
    _get(s, code)
    return executor.script(s.gap_plan(code))


@router.post("/personas/{code}/members")
def add_member(code: str, body: MemberIn, user: UserCtx = Depends(require_admin)):
    s = engine.snapshot()
    p = _get(s, code)
    gname = s.phys_group(p["group_name"])
    gid = s.pid(gname)
    if not gid or body.member_id not in s.principals:
        raise HTTPException(400, "grupo da persona ou membro inexistente no inventário")
    others = [x for x in s.personas_of(body.member_id) if x != code]
    m = s.principals[body.member_id]
    plan = [{"op": "add_member", "group": gname, "group_id": gid, "member_id": body.member_id,
             "member_name": s.label(body.member_id), "member_type": m["type"]}]
    title = f"Adicionar {s.label(body.member_id)} à persona {code}" + (f" (já está em {', '.join(others)})" if others else "")
    return workflow.create("membership_add", title, user.email, plan, payload={"persona": code, "conflicts": others},
                           target=code, duration_days=body.duration_days, justification=body.justification,
                           impact=s.impact(plan))


@router.post("/personas/{code}/members/{member_id}/remove")
def remove_member(code: str, member_id: str, user: UserCtx = Depends(require_admin)):
    s = engine.snapshot()
    p = _get(s, code)
    gname = s.phys_group(p["group_name"])
    gid = s.pid(gname)
    if not gid or member_id not in s.members.get(gid, set()):
        raise HTTPException(400, "não é membro direto da persona")
    plan = [{"op": "remove_member", "group": gname, "group_id": gid, "member_id": member_id,
             "member_name": s.label(member_id), "member_type": (s.principals.get(member_id) or {}).get("type")}]
    return workflow.create("membership_remove", f"Remover {s.label(member_id)} da persona {code}", user.email, plan,
                           payload={"persona": code}, target=code, impact=s.impact(plan))


@router.get("/personas/{code}/versions/{version}")
def version(code: str, version: int, user: UserCtx = Depends(require_view)):
    row = db.query_one("SELECT * FROM persona_versions WHERE persona_code = %s AND version = %s", (code, version))
    if not row:
        raise HTTPException(404, "versão não encontrada")
    return row


@router.post("/personas/{code}/rollback/{version}")
def rollback(code: str, version: int, user: UserCtx = Depends(require_admin)):
    row = db.query_one("SELECT snapshot FROM persona_versions WHERE persona_code = %s AND version = %s",
                       (code, version))
    if not row:
        raise HTTPException(404, "versão não encontrada")
    snap = row["snapshot"]
    change = PersonaChange(grants=[GrantRow(**g) for g in snap.get("grants", [])],
                           capabilities=snap.get("capabilities"), description=snap.get("description"),
                           justification=f"Rollback para a versão {version}")
    return propose(code, change, user)
