"""Regras e alertas: listar, reconhecer, resolver e corrigir (quando há correção automática)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server import db, engine, rules, workflow
from server.rbac import UserCtx, require_admin, require_view

router = APIRouter(prefix="/api")

RULES = {
    "grant_outside_model": "GRANT fora do modelo",
    "direct_user_grant": "GRANT direto a usuário",
    "human_write_prod": "Escrita humana em produção",
    "persona_drift": "Persona fora do modelo",
    "persona_group_missing": "Grupo de persona inexistente",
    "clearance_drift": "Clearance sem GRANTs do domínio",
    "clearance_group_missing": "Grupo de clearance inexistente",
    "multiple_personas": "Mais de uma persona",
    "no_persona": "Usuários sem persona",
    "schema_unregistered": "Schema de domínio sem cadastro",
    "clearance_bypass": "Dado sensível sem clearance",
    "self_grant": "Auto-atribuição de acesso",
    "admin_sensitive_read": "Admin lendo dado sensível",
    "creation_without_capability": "Criação sem capacidade",
    "agent_creation": "Criação por agente/SP",
}


class StatusIn(BaseModel):
    status: str


@router.get("/alerts")
def list_alerts(status: str | None = "open", severity: str | None = None, rule: str | None = None,
                user: UserCtx = Depends(require_view)):
    where, params = [], []
    if status == "open":
        where.append("status <> 'resolved'")
    elif status:
        where.append("status = %s")
        params.append(status)
    if severity:
        where.append("severity = %s")
        params.append(severity)
    if rule:
        where.append("rule = %s")
        params.append(rule)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = db.query(f"""SELECT * FROM alerts {clause}
                        ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                                 last_seen DESC LIMIT 500""", tuple(params))
    counts = db.query("SELECT rule, severity, count(*) AS n FROM alerts WHERE status <> 'resolved' GROUP BY 1, 2")
    return {"alerts": rows, "counts": counts, "rules": RULES}


@router.patch("/alerts/{alert_id}")
def set_status(alert_id: int, body: StatusIn, user: UserCtx = Depends(require_view)):
    if body.status not in ("open", "acknowledged", "resolved"):
        raise HTTPException(400, "status inválido")
    if user.is_auditor and not (user.is_admin or user.is_dpo):
        raise HTTPException(403, "auditor não altera alertas")
    row = db.execute("""UPDATE alerts SET status = %s,
                          resolved_by = CASE WHEN %s = 'resolved' THEN %s ELSE NULL END,
                          resolved_at = CASE WHEN %s = 'resolved' THEN now() ELSE NULL END
                        WHERE id = %s RETURNING *""", (body.status, body.status, user.email, body.status, alert_id))
    if not row:
        raise HTTPException(404, "alerta não encontrado")
    return row


@router.post("/alerts/{alert_id}/fix")
def fix(alert_id: int, user: UserCtx = Depends(require_admin)):
    a = db.query_one("SELECT * FROM alerts WHERE id = %s", (alert_id,))
    if not a or not a["fixable"]:
        raise HTTPException(400, "alerta sem correção automática")
    s = engine.snapshot()
    if a["rule"] == "persona_drift":
        code = a["object"]
        plan = s.gap_plan(code)
        if not plan:
            raise HTTPException(400, "persona já está conforme")
        return workflow.create("alert_fix", f"Corrigir: {a['title']}", user.email, plan,
                               payload={"alert_id": alert_id, "persona": code}, target=code, impact=s.impact(plan))
    if a["rule"] == "clearance_drift":
        plan = s.clearance_plan(a["object"])
        if not plan:
            raise HTTPException(400, "clearance já está conforme")
        return workflow.create("alert_fix", f"Corrigir: {a['title']}", user.email, plan,
                               payload={"alert_id": alert_id, "domain": a["object"]},
                               target=f"clearance:{a['object']}", impact=s.impact(plan))
    raise HTTPException(400, "regra sem correção automática")


@router.post("/alerts/evaluate")
def evaluate(user: UserCtx = Depends(require_admin)):
    engine.invalidate()
    return {"open": rules.evaluate()}
