"""Regras contínuas sobre o inventário → alertas (idempotente, auto-resolve)."""

from __future__ import annotations

import json
from collections import defaultdict

import psycopg2.extras

from server import db, engine
from server.engine import ALL, Snapshot

WRITE_PRIVS = {"MODIFY", ALL}
SENSITIVE = {"restricted", "critical"}


def _app_principals(s: Snapshot) -> set[str]:
    return {p.lower() for p in (s.settings.get("app_principals") or [])}


def _allowed_grantee(s: Snapshot, pid: str | None, pname: str) -> bool:
    if pname.lower() in _app_principals(s):
        return True
    p = s.principals.get(pid or "")
    return bool(p and p["type"] == "group" and p.get("group_class") in ("persona", "clearance"))


def evaluate() -> int:
    s = engine.load()
    out: list[dict] = []
    add = out.append
    prd_catalogs = {c["physical_name"] for c in s.catalogs.values() if c["env"] == "prd"}
    managed = {c["physical_name"] for c in s.catalogs.values() if c["managed"]}

    # 1–3: GRANTs fora do modelo, diretos a usuário, escrita humana em produção
    outside: dict[str, list[dict]] = defaultdict(list)
    for sec, rows in s.grants.items():
        if sec.split(".")[0] not in managed:
            continue
        for pname, pid, priv in rows:
            p = s.principals.get(pid or "") or {}
            if not _allowed_grantee(s, pid, pname):
                outside[pid or pname].append({"securable": sec, "privilege": priv})
            if priv in WRITE_PRIVS and sec.split(".")[0] in prd_catalogs and pname.lower() not in _app_principals(s):
                if p.get("type") == "user":
                    humans = [pid]
                elif p.get("type") == "group":
                    humans = [m for m in s.transitive_members(pid) if s.is_human(m)]
                else:
                    humans = []
                if humans:
                    add({"rule": "human_write_prod", "severity": "critical",
                         "title": f"{len(humans)} pessoa(s) podem escrever em produção via {s.label(pid)}",
                         "principal": pid, "object": sec,
                         "detail": {"privilege": priv, "via": pname, "people": [s.label(h) for h in humans][:50]}})
    for key, items in outside.items():
        p = s.principals.get(key) or {}
        cls = p.get("group_class") if p.get("type") == "group" else p.get("type")
        if p.get("type") == "user":
            sev = "critical" if any(i["privilege"] in WRITE_PRIVS for i in items) else "warning"
            add({"rule": "direct_user_grant", "severity": sev,
                 "title": f"GRANT direto ao usuário {s.label(key)} ({len(items)})",
                 "principal": key, "object": items[0]["securable"], "detail": {"grants": items}})
            continue
        sev = "critical" if cls == "clone" else "warning"
        members = len([m for m in s.transitive_members(key) if s.is_human(m)]) if p.get("type") == "group" else 0
        add({"rule": "grant_outside_model", "severity": sev,
             "title": f"{s.label(key)}: {len(items)} GRANT(s) fora do modelo" + (f" · {members} pessoa(s)" if members else ""),
             "principal": key, "object": None,
             "detail": {"class": cls, "grants": items, "members": members}})

    # 4: drift das personas
    for code, persona in s.personas.items():
        gap = s.persona_gap(code)
        if not gap["group_exists"]:
            add({"rule": "persona_group_missing", "severity": "critical",
                 "title": f"Grupo da persona {code} não existe ({gap['group']})", "principal": None,
                 "object": gap["group"], "detail": {}})
            continue
        miss, extra = gap["counts"].get("missing", 0), gap["counts"].get("extra", 0)
        if miss or extra:
            add({"rule": "persona_drift", "severity": "warning", "fixable": True,
                 "title": f"Persona {code}: {miss} faltando · {extra} fora do modelo",
                 "principal": gap["group_id"], "object": code, "detail": {"missing": miss, "extra": extra}})

    # 4b: grupos de clearance sem os GRANTs do domínio
    for code, d in s.domains.items():
        if not d.get("clearance_group"):
            continue
        gname = s.phys_group(d["clearance_group"])
        if not s.pid(gname):
            add({"rule": "clearance_group_missing", "severity": "warning",
                 "title": f"Grupo de clearance {gname} não existe", "principal": None, "object": code, "detail": {}})
            continue
        plan = s.clearance_plan(code)
        if plan:
            add({"rule": "clearance_drift", "severity": "warning", "fixable": True,
                 "title": f"Clearance de {d['name']} sem os GRANTs do domínio ({len(plan)} operações)",
                 "principal": s.pid(gname), "object": code, "detail": {"plan": plan}})

    # 5: usuários sem persona ou com mais de uma
    no_persona = []
    for pid, p in s.principals.items():
        if p["type"] != "user" or not p.get("in_scope"):
            continue
        ps = s.personas_of(pid)
        if len(ps) > 1:
            add({"rule": "multiple_personas", "severity": "warning",
                 "title": f"{s.label(pid)} está em {len(ps)} personas", "principal": pid, "object": None,
                 "detail": {"personas": ps}})
        elif not ps:
            no_persona.append(s.label(pid))
    if no_persona:
        add({"rule": "no_persona", "severity": "info", "title": f"{len(no_persona)} usuário(s) sem persona",
             "principal": None, "object": None, "detail": {"users": sorted(no_persona)}})

    # 6: schema de domínio sem cadastro
    prd = (s.catalogs.get("data_products_prd") or {}).get("physical_name")
    known = {d["schema_name"] for d in s.domains.values()}
    for sch in s.product_schemas(prd) if prd else []:
        name = sch.split(".", 1)[1]
        if name not in known:
            add({"rule": "schema_unregistered", "severity": "warning",
                 "title": f"Schema de domínio sem cadastro: {name}", "principal": None, "object": sch,
                 "detail": {"hint": "cadastre o domínio (dono, sensibilidade) e aplique os GRANTs das personas"}})

    # 7: dado sensível lido sem clearance
    for table, sec in s.securables.items():
        if sec["type"] not in ("table", "view"):
            continue
        sens = s.sensitivity(table)
        if sens not in SENSITIVE:
            continue
        dom = s.domains.get(sec.get("domain") or "")
        cl_gid = s.pid(s.phys_group(dom["clearance_group"])) if dom and dom.get("clearance_group") else None
        readers = s.who_can_read(table)
        bypass = [r for r in readers if not (cl_gid and cl_gid in s.groups_of(r))]
        if bypass:
            add({"rule": "clearance_bypass", "severity": "critical",
                 "title": f"{len(bypass)} identidade(s) leem {sec['table_name']} ({sens}) sem clearance",
                 "principal": None, "object": table,
                 "detail": {"sensitivity": sens, "clearance_group": dom.get("clearance_group") if dom else None,
                            "readers": sorted(s.label(r) for r in bypass)[:100],
                            "note": "GRANT no catalog inteiro alcança tabelas restritas; o bloqueio efetivo "
                                    "exige clearance + política ABAC (ou schema dedicado)."}})

    # 8: auto-atribuição de permissão
    for e in db.query("SELECT event_time, actor, securable, grantee FROM inv_permission_events "
                      "WHERE grantee IS NOT NULL AND lower(actor) = lower(grantee)"):
        pid = s.pid(e["actor"])
        add({"rule": "self_grant", "severity": "critical",
             "title": f"{s.label(pid) if pid else e['actor']} concedeu acesso a si mesmo em {e['securable']}",
             "principal": pid or e["actor"], "object": e["securable"],
             "detail": {"event_time": str(e["event_time"])}})

    # 9: admin lendo dado sensível
    admin = s.personas.get("platform-admin")
    admin_gid = s.pid(s.phys_group(admin["group_name"])) if admin else None
    if admin_gid:
        admins = set(s.transitive_members(admin_gid))
        for u in db.query("SELECT principal_id, securable, SUM(n) AS n, MAX(day) AS last FROM inv_usage "
                          "WHERE action = 'read' AND day >= current_date - 30 GROUP BY 1, 2"):
            if u["principal_id"] in admins and s.sensitivity(u["securable"]) in SENSITIVE:
                add({"rule": "admin_sensitive_read", "severity": "critical",
                     "title": f"Admin {s.label(u['principal_id'])} leu {u['securable'].split('.')[-1]}",
                     "principal": u["principal_id"], "object": u["securable"],
                     "detail": {"reads": int(u["n"]), "last": str(u["last"])}})

    # 10: criação sem a capacidade da persona
    for c in db.query("SELECT principal_id, capability, asset_name, event_time FROM inv_creations "
                      "WHERE event_time >= now() - interval '60 days'"):
        pid = c["principal_id"]
        p = s.principals.get(pid) or {}
        if p.get("type") == "user":
            caps = set().union(*[s.persona_caps.get(x, set()) for x in s.personas_of(pid)]) if s.personas_of(pid) else set()
            if c["capability"] not in caps:
                add({"rule": "creation_without_capability", "severity": "warning",
                     "title": f"{s.label(pid)} criou {c['capability']} sem essa capacidade na persona",
                     "principal": pid, "object": c["asset_name"],
                     "detail": {"capability": c["capability"], "personas": s.personas_of(pid),
                                "event_time": str(c["event_time"])}})
        elif p.get("type") == "sp":
            add({"rule": "agent_creation", "severity": "info",
                 "title": f"Service principal {s.label(pid)} criou {c['capability']}",
                 "principal": pid, "object": c["asset_name"],
                 "detail": {"capability": c["capability"], "event_time": str(c["event_time"])}})

    return _upsert(out)


def _upsert(alerts: list[dict]) -> int:
    uniq: dict[str, dict] = {}
    for a in alerts:  # a mesma condição pode aparecer em várias linhas de GRANT
        uniq.setdefault(f"{a['rule']}|{a.get('principal') or ''}|{a.get('object') or ''}", a)
    rows = [(a["rule"], a["severity"], a["title"], a.get("principal"), a.get("object"),
             json.dumps(a.get("detail") or {}, default=str), bool(a.get("fixable")), key) for key, a in uniq.items()]
    with db.connection() as conn:
        with conn.cursor() as cur:
            if rows:
                psycopg2.extras.execute_values(
                    cur,
                    """INSERT INTO alerts (rule, severity, title, principal, object, detail, fixable, dedup_key)
                       VALUES %s
                       ON CONFLICT (dedup_key) DO UPDATE SET severity = EXCLUDED.severity, title = EXCLUDED.title,
                         detail = EXCLUDED.detail, fixable = EXCLUDED.fixable, last_seen = now(),
                         status = CASE WHEN alerts.status = 'resolved' THEN 'open' ELSE alerts.status END,
                         resolved_by = CASE WHEN alerts.status = 'resolved' THEN NULL ELSE alerts.resolved_by END,
                         resolved_at = CASE WHEN alerts.status = 'resolved' THEN NULL ELSE alerts.resolved_at END""",
                    rows, page_size=500)
            cur.execute("""UPDATE alerts SET status = 'resolved', resolved_by = 'auto', resolved_at = now()
                           WHERE status <> 'resolved' AND NOT (dedup_key = ANY(%s))""", (list(uniq) or [""],))
            cur.execute("SELECT count(*) FROM alerts WHERE status <> 'resolved'")
            return int(cur.fetchone()[0])
