"""Camada de aplicação: executa planos (GRANT/REVOKE e membros de grupo).

Modo direto: o service principal do app aplica no Unity Catalog e no SCIM da
conta. Também gera o script equivalente para revisão. Após aplicar, atualiza
o espelho do inventário só dos objetos/grupos tocados e invalida o cache.

Operações:
  {"op": "grant"|"revoke", "sec_type", "securable", "principal", "privileges": [...]}
  {"op": "add_member"|"remove_member", "group", "group_id", "member_id", "member_name", "member_type"}
"""

from __future__ import annotations

import json

from databricks.sdk import WorkspaceClient

from server import db, engine, uc
from server import identity as idn
from server import inventory
from server.config import get_workspace_client


def describe(op: dict) -> str:
    if op["op"] in ("grant", "revoke"):
        verb = "GRANT" if op["op"] == "grant" else "REVOKE"
        return f"{verb} {', '.join(op['privileges'])} em {op['securable']} → {op['principal']}"
    verb = "adicionar" if op["op"] == "add_member" else "remover"
    return f"{verb} {op.get('member_name') or op['member_id']} {'em' if verb == 'adicionar' else 'de'} {op['group']}"


def script(ops: list[dict]) -> str:
    lines = ["-- Lakeguard — plano gerado para revisão", ""]
    for op in ops:
        if op["op"] in ("grant", "revoke"):
            lines.append(uc.grant_sql(op["sec_type"], op["securable"], op["principal"], op["privileges"],
                                      revoke=op["op"] == "revoke"))
        else:
            act = "add" if op["op"] == "add_member" else "remove"
            lines.append(f"-- SCIM PATCH Groups/{op['group_id']} ({op['group']}): {act} member "
                         f"{op['member_id']} ({op.get('member_name') or ''})")
    return "\n".join(lines) + "\n"


def apply(ops: list[dict], actor: str, w: WorkspaceClient | None = None, dry_run: bool = False) -> dict:
    w = w or get_workspace_client()
    results, touched_secs, touched_groups = [], set(), set()
    ok = True
    for op in ops:
        r = {"op": describe(op), "ok": True}
        if dry_run:
            r["dry_run"] = True
            results.append(r)
            continue
        try:
            if op["op"] == "grant":
                uc.update_grants(w, op["sec_type"], op["securable"], op["principal"], add=op["privileges"])
                touched_secs.add((op["sec_type"], op["securable"]))
            elif op["op"] == "revoke":
                uc.update_grants(w, op["sec_type"], op["securable"], op["principal"], remove=op["privileges"])
                touched_secs.add((op["sec_type"], op["securable"]))
            elif op["op"] == "add_member":
                idn.add_member(w, op["group_id"], op["member_id"])
                touched_groups.add(op["group_id"])
            elif op["op"] == "remove_member":
                idn.remove_member(w, op["group_id"], op["member_id"])
                touched_groups.add(op["group_id"])
        except Exception as ex:  # noqa: BLE001
            ok = False
            r.update(ok=False, error=str(ex)[:500])
        results.append(r)
    if not dry_run and (touched_secs or touched_groups):
        try:
            with db.connection() as conn:
                inventory.refresh_targets(w, conn, sorted(touched_secs), sorted(touched_groups))
        except Exception as ex:  # noqa: BLE001
            results.append({"op": "atualizar inventário", "ok": False, "error": str(ex)[:300]})
        engine.invalidate()
    log(actor, "apply" if not dry_run else "dry_run", None, {"ok": ok, "ops": len(ops), "results": results})
    return {"ok": ok, "results": results}


def log(actor: str, action: str, target: str | None, detail: dict | None = None) -> None:
    db.execute("INSERT INTO action_log (actor, action, target, detail) VALUES (%s,%s,%s,%s)",
               (actor, action, target, json.dumps(detail or {}, default=str)))
