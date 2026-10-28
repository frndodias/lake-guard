"""Migração (tombamento) dos grupos legados para o modelo de personas.

Sugestão automática por grupo (o admin pode editar):
  delete          — sem membros (resíduo)
  shrink_to_floor — clone de "users": reduzir ao piso universal (BROWSE)
  to_sp           — grupo de agentes/SPs: SP por ferramenta, com escopo próprio
  to_clearance    — acesso concentrado em domínio sensível → clearance-{domínio}
  to_persona      — padrão de acesso parecido com uma persona (similaridade)
Ondas geram um plano (membros → destino, depois saem do legado) com rollback.
"""

from __future__ import annotations

from server import db
from server.engine import ALL, Snapshot

LEGACY_CLASSES = ("legacy", "clone", "system")


def _tokens_from_grants(s: Snapshot, items: list[tuple[str, str]]) -> set[str]:
    """(securable, privilege) → tokens 'read:<logical>/<schema>' e 'create:<logical>'."""
    toks = set()
    for sec, priv in items:
        parts = sec.split(".")
        logical = s.phys_to_logical.get(parts[0], parts[0])
        if priv in ("SELECT", ALL):
            if len(parts) == 1:
                schemas = [c.split(".", 1)[1] for c in s.children.get(sec, [])] or ["*"]
            else:
                schemas = [parts[1]]
            toks |= {f"read:{logical}/{x}" for x in schemas}
        if priv in ("CREATE_TABLE", "MODIFY", ALL):
            toks.add(f"create:{logical}")
    return toks


def _group_tokens(s: Snapshot, gid: str) -> set[str]:
    items = [(sec, priv) for sec, rows in s.grants.items() for _, ppid, priv in rows if ppid == gid]
    return _tokens_from_grants(s, items)


def _persona_tokens(s: Snapshot, code: str) -> set[str]:
    items = [(d["securable"], p) for d in s.expand_persona(code) for p in d["privileges"]]
    return _tokens_from_grants(s, items)


def suggest(s: Snapshot) -> list[dict]:
    out = []
    persona_toks = {c: _persona_tokens(s, c) for c in s.personas}
    sens_schema = {d["schema_name"]: d for d in s.domains.values() if d["sensitivity"] != "normal"}
    for gid, g in s.principals.items():
        if g["type"] != "group" or g.get("group_class") not in LEGACY_CLASSES or not g.get("in_scope"):
            continue
        humans = [m for m in s.transitive_members(gid) if s.is_human(m)]
        direct = sorted(s.members.get(gid, set()))
        toks = _group_tokens(s, gid)
        base = s.base_name(g["name"])
        cls = g["group_class"]
        sugg = {"group": g["name"], "group_id": gid, "class": cls, "members": len(direct),
                "humans": len(humans), "grants": sum(1 for rows in s.grants.values() for r in rows if r[1] == gid),
                "action": "keep", "target": None, "rationale": "", "score": None}
        if cls == "clone":
            sugg.update(action="shrink_to_floor", rationale="Clone automático do grupo users: concede a todos. "
                        "Reduzir ao piso universal (BROWSE) depois que todos tiverem persona.")
        elif cls == "system":
            sugg.update(action="to_sp", rationale="Grupo de agentes/SPs sem categoria no modelo: um SP por "
                        "ferramenta, com escopo próprio (e OBO para agentes que agem por humanos).")
        elif not direct:
            sugg.update(action="delete", rationale="Sem membros: provável resíduo.")
        else:
            sens_hits = {sens_schema[t.split("/", 1)[1]]["code"] for t in toks
                         if t.startswith("read:data_products_prd/") and t.split("/", 1)[1] in sens_schema}
            if sens_hits and len(sens_hits) == 1 and len(toks) <= 4:
                dom = next(iter(sens_hits))
                sugg.update(action="to_clearance", target=dom,
                            rationale=f"Acesso concentrado no domínio sensível {dom}: hoje faz papel de clearance.")
            else:
                best, score = None, 0.0
                for code, ptoks in persona_toks.items():
                    if not toks or not ptoks:
                        continue
                    j = len(toks & ptoks) / len(toks | ptoks)
                    if j > score:
                        best, score = code, j
                if best:
                    sugg.update(action="to_persona", target=best, score=round(score, 2),
                                rationale=f"Padrão de acesso mais parecido com {best} (similaridade {score:.0%}).")
        out.append(sugg)
    return sorted(out, key=lambda x: (x["class"], x["group"]))


def sync_mappings(s: Snapshot, actor: str = "sistema") -> list[dict]:
    """Grava sugestões novas sem sobrescrever o que o admin já editou."""
    sugg = suggest(s)
    for x in sugg:
        db.execute("""INSERT INTO migration_mappings (legacy_group, action, target, suggested, rationale, updated_by)
                      VALUES (%s,%s,%s,TRUE,%s,%s)
                      ON CONFLICT (legacy_group) DO UPDATE SET action = EXCLUDED.action, target = EXCLUDED.target,
                        rationale = EXCLUDED.rationale, updated_at = now()
                      WHERE migration_mappings.suggested AND migration_mappings.status = 'planned'""",
                   (x["group"], x["action"], x["target"], x["rationale"], actor))
    rows = {r["legacy_group"]: r for r in db.query("SELECT * FROM migration_mappings")}
    for x in sugg:
        m = rows.get(x["group"]) or {}
        x["mapping"] = m
        x["suggested_action"], x["suggested_target"] = x["action"], x["target"]
        if m:
            x["action"], x["target"] = m["action"], m["target"]
    return sugg


def _member_op(s: Snapshot, kind: str, group_name: str, mid: str) -> dict:
    p = s.principals.get(mid) or {}
    return {"op": kind, "group": group_name, "group_id": s.pid(group_name), "member_id": mid,
            "member_name": s.label(mid), "member_type": p.get("type", "user")}


def wave_plan(s: Snapshot, groups: list[str]) -> tuple[list[dict], list[dict], list[str]]:
    """(ops, inverse_ops, notas) para migrar os grupos legados da onda."""
    maps = {r["legacy_group"]: r for r in db.query("SELECT * FROM migration_mappings WHERE legacy_group = ANY(%s)",
                                                    (groups,))}
    ops, notes = [], []
    floor = s.settings.get("floor_privileges") or {}
    for gname in groups:
        gid = s.pid(gname)
        m = maps.get(gname)
        if not gid or not m:
            notes.append(f"{gname}: sem mapeamento — ignorado")
            continue
        action, target = m["action"], m["target"]
        direct = sorted(s.members.get(gid, set()))
        if action in ("to_persona", "to_clearance"):
            if action == "to_persona":
                dest = s.personas.get(target or "")
                dest_name = s.phys_group(dest["group_name"]) if dest else None
            else:
                dom = s.domains.get(target or "")
                dest_name = s.phys_group(dom["clearance_group"]) if dom and dom.get("clearance_group") else None
            dest_id = s.pid(dest_name) if dest_name else None
            if not dest_id:
                notes.append(f"{gname}: grupo de destino inexistente ({dest_name})")
                continue
            for mid in direct:
                p = s.principals.get(mid) or {}
                if p.get("type") == "group":
                    notes.append(f"{gname}: membro grupo {s.label(mid)} não é movido automaticamente")
                    continue
                if dest_id not in s.groups_of(mid):
                    ops.append(_member_op(s, "add_member", dest_name, mid))
                ops.append(_member_op(s, "remove_member", gname, mid))
        elif action == "delete":
            for sec, rows in s.grants.items():
                privs = [priv for _, ppid, priv in rows if ppid == gid]
                if privs:
                    st = (s.securables.get(sec) or {}).get("type", "catalog")
                    ops.append({"op": "revoke", "sec_type": "table" if st == "view" else st, "securable": sec,
                                "principal": gname, "privileges": privs})
            for mid in direct:
                ops.append(_member_op(s, "remove_member", gname, mid))
        elif action == "shrink_to_floor":
            for sec, rows in s.grants.items():
                logical = s.phys_to_logical.get(sec.split(".")[0], "")
                keep = set(floor.get(logical, [])) if "." not in sec else set()
                privs = [priv for _, ppid, priv in rows if ppid == gid and priv not in keep]
                if privs:
                    st = (s.securables.get(sec) or {}).get("type", "catalog")
                    ops.append({"op": "revoke", "sec_type": "table" if st == "view" else st, "securable": sec,
                                "principal": gname, "privileges": privs})
            for logical, privs in floor.items():
                cat = s.catalogs.get(logical)
                if not cat:
                    continue
                have = {priv for _, ppid, priv in s.grants.get(cat["physical_name"], []) if ppid == gid}
                missing = [p for p in privs if p not in have]
                if missing:
                    ops.append({"op": "grant", "sec_type": "catalog", "securable": cat["physical_name"],
                                "principal": gname, "privileges": missing})
        elif action == "to_sp":
            notes.append(f"{gname}: migração de agentes é manual (SP por ferramenta) — sem operações automáticas")
    inverse = [_inverse(o) for o in reversed(ops)]
    return ops, inverse, notes


def _inverse(op: dict) -> dict:
    flip = {"grant": "revoke", "revoke": "grant", "add_member": "remove_member", "remove_member": "add_member"}
    return {**op, "op": flip[op["op"]]}
