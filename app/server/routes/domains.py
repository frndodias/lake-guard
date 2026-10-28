"""Domínios (schemas da camada product), sensibilidade, clearance e stewards."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server import db, engine, executor, workflow
from server.rbac import UserCtx, require_admin, require_view

router = APIRouter(prefix="/api")


class DomainIn(BaseModel):
    code: str = Field(..., pattern="^[a-z0-9_-]+$")
    name: str
    schema_name: str
    owner: str | None = None
    sensitivity: str = Field("normal", pattern="^(normal|restricted|critical)$")
    clearance_group: str | None = None
    description: str | None = None


class StewardIn(BaseModel):
    principal: str
    principal_type: str = Field("user", pattern="^(user|group)$")


@router.get("/domains")
def list_domains(user: UserCtx = Depends(require_view)):
    s = engine.snapshot()
    stewards: dict[str, list[str]] = {}
    for r in db.query("SELECT principal, domain FROM app_roles WHERE role = 'steward' AND domain IS NOT NULL"):
        stewards.setdefault(r["domain"], []).append(r["principal"])
    prd = (s.catalogs.get("data_products_prd") or {}).get("physical_name", "")
    out = []
    for d in sorted(s.domains.values(), key=lambda x: x["name"]):
        full = f"{prd}.{d['schema_name']}"
        tables = s.tables_under(full)
        cl = s.phys_group(d["clearance_group"]) if d.get("clearance_group") else None
        cl_id = s.pid(cl) if cl else None
        out.append({**d, "schema_full_name": full, "schema_exists": full in s.securables, "tables": len(tables),
                    "sensitive_tables": sum(1 for t in tables if (s.securables[t].get("sensitivity"))),
                    "clearance_physical": cl, "clearance_exists": bool(cl_id),
                    "clearance_members": [s.label(m) for m in s.transitive_members(cl_id)] if cl_id else [],
                    "clearance_plan": s.clearance_plan(d["code"]),
                    "stewards": stewards.get(d["code"], [])})
    known = {d["schema_name"] for d in s.domains.values()}
    unregistered = [x.split(".", 1)[1] for x in s.product_schemas(prd) if x.split(".", 1)[1] not in known] if prd else []
    return {"domains": out, "unregistered_schemas": unregistered}


@router.post("/domains")
def upsert_domain(body: DomainIn, user: UserCtx = Depends(require_admin)):
    row = db.execute("""INSERT INTO domains (code, name, schema_name, owner, sensitivity, clearance_group, description)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, schema_name = EXCLUDED.schema_name,
                          owner = EXCLUDED.owner, sensitivity = EXCLUDED.sensitivity,
                          clearance_group = EXCLUDED.clearance_group, description = EXCLUDED.description
                        RETURNING *""",
                     (body.code, body.name, body.schema_name, body.owner, body.sensitivity,
                      body.clearance_group or None, body.description))
    db.execute("UPDATE inv_securables SET domain = %s WHERE catalog = "
               "(SELECT physical_name FROM catalogs WHERE logical_name = 'data_products_prd') AND schema_name = %s",
               (body.code, body.schema_name))
    executor.log(user.email, "domain_upsert", body.code, body.model_dump())
    engine.invalidate()
    return row


@router.post("/domains/{code}/apply-clearance")
def apply_clearance(code: str, user: UserCtx = Depends(require_admin)):
    s = engine.snapshot()
    if code not in s.domains:
        raise HTTPException(404, "domínio não encontrado")
    plan = s.clearance_plan(code)
    if not plan:
        raise HTTPException(400, "clearance já está com os GRANTs do modelo (ou o grupo não existe)")
    return workflow.create("gap_fix", f"GRANTs do clearance de {s.domains[code]['name']}", user.email, plan,
                           payload={"domain": code}, target=f"clearance:{code}", impact=s.impact(plan))


@router.post("/domains/{code}/stewards")
def add_steward(code: str, body: StewardIn, user: UserCtx = Depends(require_admin)):
    if not db.query_one("SELECT 1 AS ok FROM domains WHERE code = %s", (code,)):
        raise HTTPException(404, "domínio não encontrado")
    db.execute("""INSERT INTO app_roles (principal, principal_type, role, domain, granted_by)
                  VALUES (%s,%s,'steward',%s,%s) ON CONFLICT DO NOTHING""",
               (body.principal, body.principal_type, code, user.email))
    executor.log(user.email, "steward_add", code, body.model_dump())
    return {"ok": True}


@router.delete("/domains/{code}/stewards/{principal}")
def remove_steward(code: str, principal: str, user: UserCtx = Depends(require_admin)):
    db.execute("DELETE FROM app_roles WHERE role = 'steward' AND domain = %s AND lower(principal) = lower(%s)",
               (code, principal))
    executor.log(user.email, "steward_remove", code, {"principal": principal})
    return {"ok": True}
