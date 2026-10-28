"""Ciclo de vida das mudanças: proposta → aprovação → aplicação → expiração.

Quem decide não executa: as pessoas aprovam aqui e o SP do app aplica.
Regras:
  * quem pede não aprova (exceto com settings.allow_self_approval — modo demo)
  * acesso a dado restrito (clearance) → steward do domínio; domínio 'critical' → + DPO
  * mudanças de persona, correções e migração → admin
  * acesso temporário expira sozinho (job / botão "processar expirações")
"""

from __future__ import annotations

import datetime as dt
import json

from databricks.sdk import WorkspaceClient

from server import db, engine, executor
from server.rbac import UserCtx
from server.seed import snapshot_persona

ACCESS_KINDS = ("access_request", "membership_add")


def _j(v) -> str:
    return json.dumps(v, default=str)


def create(kind: str, title: str, actor: str, plan: list[dict], payload: dict | None = None,
           target: str | None = None, domain: str | None = None, requires_dpo: bool = False,
           duration_days: int | None = None, justification: str | None = None,
           impact: dict | None = None) -> dict:
    row = db.execute(
        """INSERT INTO change_requests (kind, title, target, domain, payload, plan, impact, justification,
                                        duration_days, requires_dpo, requested_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (kind, title, target, domain, _j(payload or {}), _j(plan), _j(impact) if impact else None,
         justification, duration_days, requires_dpo, actor))
    executor.log(actor, f"request:{kind}", target, {"id": row["id"], "title": title})
    return row


def get(req_id: int) -> dict | None:
    return db.query_one("SELECT * FROM change_requests WHERE id = %s", (req_id,))


def _self_ok() -> bool:
    row = db.query_one("SELECT value FROM settings WHERE key = 'allow_self_approval'")
    return bool(row and row["value"])


def stages_for(user: UserCtx, req: dict) -> list[str]:
    """Etapas que este usuário pode aprovar agora: 'approver' e/ou 'dpo'."""
    if req["status"] != "pending":
        return []
    if req["requested_by"].lower() == (user.email or "").lower() and not _self_ok():
        return []
    out = []
    if not req["approved_by"]:
        if req["kind"] in ACCESS_KINDS and req["domain"]:
            if user.is_steward(req["domain"]) or user.is_admin:
                out.append("approver")
        elif user.is_admin:
            out.append("approver")
    if req["requires_dpo"] and not req["dpo_approved_by"] and user.is_dpo:
        same_person = req["approved_by"] and req["approved_by"].lower() == (user.email or "").lower()
        if (not same_person and not out) or _self_ok():
            out.append("dpo")
    return out


def approve(req_id: int, user: UserCtx, note: str | None = None) -> dict:
    req = get(req_id)
    if not req:
        raise ValueError("pedido não encontrado")
    stages = stages_for(user, req)
    if not stages:
        raise PermissionError("você não pode aprovar este pedido (papel, etapa ou auto-aprovação)")
    sets, params = [], []
    if "approver" in stages:
        sets += ["approved_by = %s", "approved_at = now()"]
        params.append(user.email)
    if "dpo" in stages:
        sets += ["dpo_approved_by = %s", "dpo_approved_at = now()"]
        params.append(user.email)
    if note:
        sets.append("decision_note = %s")
        params.append(note)
    req = db.execute(f"UPDATE change_requests SET {', '.join(sets)} WHERE id = %s RETURNING *",
                     (*params, req_id))
    executor.log(user.email, "approve", str(req_id), {"stages": stages})
    if req["approved_by"] and (not req["requires_dpo"] or req["dpo_approved_by"]):
        return execute(req, user.email)
    return req


def reject(req_id: int, user: UserCtx, note: str | None = None) -> dict:
    req = get(req_id)
    if not req or req["status"] != "pending":
        raise ValueError("pedido não está pendente")
    if not (stages_for(user, req) or user.is_admin):
        raise PermissionError("sem permissão para rejeitar")
    executor.log(user.email, "reject", str(req_id), {"note": note})
    return db.execute("UPDATE change_requests SET status = 'rejected', rejected_by = %s, decision_note = %s "
                      "WHERE id = %s RETURNING *", (user.email, note, req_id))


def cancel(req_id: int, user: UserCtx) -> dict:
    req = get(req_id)
    if not req or req["status"] != "pending":
        raise ValueError("pedido não está pendente")
    if req["requested_by"].lower() != (user.email or "").lower() and not user.is_admin:
        raise PermissionError("só quem pediu pode cancelar")
    return db.execute("UPDATE change_requests SET status = 'cancelled' WHERE id = %s RETURNING *", (req_id,))


def execute(req: dict, actor: str, w: WorkspaceClient | None = None) -> dict:
    plan = req["plan"] or []
    res = executor.apply(plan, actor, w=w)
    status = "applied" if res["ok"] else "failed"
    expires = None
    if res["ok"]:
        _after_apply(req, actor)
        if req["kind"] in ACCESS_KINDS and req["duration_days"]:
            expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=int(req["duration_days"]))
            for op in plan:
                if op["op"] == "add_member":
                    db.execute("""INSERT INTO manual_members (group_name, member_id, member_name, member_type,
                                    justification, approved_by, change_id, expires_at)
                                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                               (op["group"], op["member_id"], op.get("member_name") or op["member_id"],
                                op.get("member_type") or "user", req["justification"], req["approved_by"],
                                req["id"], expires))
    return db.execute("UPDATE change_requests SET status = %s, applied_at = now(), expires_at = %s, result = %s "
                      "WHERE id = %s RETURNING *", (status, expires, _j(res), req["id"]))


def _after_apply(req: dict, actor: str) -> None:
    kind, payload = req["kind"], req["payload"] or {}
    if kind == "persona_update":
        code = payload["persona"]
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE personas SET version = version + 1, description = COALESCE(%s, description), "
                            "updated_by = %s, updated_at = now() WHERE code = %s",
                            (payload.get("description"), actor, code))
                if "grants" in payload:
                    cur.execute("DELETE FROM persona_grants WHERE persona_code = %s", (code,))
                    for g in payload["grants"]:
                        cur.execute("INSERT INTO persona_grants (persona_code, catalog_logical, schema_scope, "
                                    "privileges) VALUES (%s,%s,%s,%s)",
                                    (code, g["catalog"], g.get("schema_scope") or None, g["privileges"]))
                if "capabilities" in payload:
                    cur.execute("DELETE FROM persona_capabilities WHERE persona_code = %s", (code,))
                    for c in payload["capabilities"]:
                        cur.execute("INSERT INTO persona_capabilities (persona_code, capability) VALUES (%s,%s)",
                                    (code, c))
                snapshot_persona(cur, code, actor, req["id"])
        engine.invalidate()
    elif kind == "membership_remove":
        for op in req["plan"]:
            if op["op"] == "remove_member":
                db.execute("UPDATE manual_members SET removed_at = now(), removed_reason = 'removido' "
                           "WHERE group_name = %s AND member_id = %s AND removed_at IS NULL",
                           (op["group"], op["member_id"]))
    elif kind == "migration_wave":
        db.execute("UPDATE migration_waves SET status = 'executed', executed_at = now() WHERE id = %s",
                   (payload["wave_id"],))
        db.execute("UPDATE migration_mappings SET status = 'migrated', updated_at = now() "
                   "WHERE legacy_group = ANY(%s)", (payload.get("groups") or [],))
    elif kind == "migration_rollback":
        db.execute("UPDATE migration_waves SET status = 'rolled_back' WHERE id = %s", (payload["wave_id"],))
        db.execute("UPDATE migration_mappings SET status = 'rolled_back', updated_at = now() "
                   "WHERE legacy_group = ANY(%s)", (payload.get("groups") or [],))
    elif kind == "alert_fix" and payload.get("alert_id"):
        db.execute("UPDATE alerts SET status = 'resolved', resolved_by = %s, resolved_at = now() WHERE id = %s",
                   (actor, payload["alert_id"]))


def revoke_access(req_id: int, user: UserCtx, reason: str = "revogado") -> dict:
    req = get(req_id)
    if not req or req["status"] != "applied" or req["kind"] not in ACCESS_KINDS:
        raise ValueError("só acessos aplicados podem ser revogados")
    if not (user.is_admin or (req["domain"] and user.is_steward(req["domain"]))):
        raise PermissionError("sem permissão para revogar")
    return _remove_access(req, user.email, "revoked", reason)


def _remove_access(req: dict, actor: str, status: str, reason: str, w: WorkspaceClient | None = None) -> dict:
    ops = [{**op, "op": "remove_member"} for op in (req["plan"] or []) if op["op"] == "add_member"]
    res = executor.apply(ops, actor, w=w)
    for op in ops:
        db.execute("UPDATE manual_members SET removed_at = now(), removed_reason = %s "
                   "WHERE change_id = %s AND member_id = %s AND removed_at IS NULL",
                   (reason, req["id"], op["member_id"]))
    return db.execute("UPDATE change_requests SET status = %s, result = %s WHERE id = %s RETURNING *",
                      (status, _j({"removal": res}), req["id"]))


def expire_due(w: WorkspaceClient | None = None, actor: str = "sistema") -> int:
    due = db.query("SELECT * FROM change_requests WHERE status = 'applied' AND expires_at IS NOT NULL "
                   "AND expires_at <= now() AND kind = ANY(%s)", (list(ACCESS_KINDS),))
    for req in due:
        _remove_access(req, actor, "expired", "expirou", w=w)
    return len(due)
