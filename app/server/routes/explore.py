"""Visão 360: identidades, grupos e assets — quem PODE × quem USA."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query

from server import db, engine
from server.engine import Snapshot
from server.rbac import UserCtx, get_user, require_view

router = APIRouter(prefix="/api")


def _usage_by(where: str, params: tuple, days: int = 90) -> list[dict]:
    return db.query(
        f"""SELECT principal_id, securable, action, SUM(n) AS n, MAX(day) AS last_day, MIN(source) AS source
            FROM inv_usage WHERE day >= current_date - %s::int AND {where}
            GROUP BY principal_id, securable, action ORDER BY SUM(n) DESC""", (days, *params))


def _klass(s: Snapshot, pid: str | None) -> str | None:
    p = s.principals.get(pid or "") or {}
    return p.get("group_class") if p.get("type") == "group" else p.get("type")


def _brief(s: Snapshot, pid: str) -> dict:
    p = s.principals.get(pid) or {"id": pid, "type": "?", "name": pid}
    return {"id": pid, "type": p["type"], "name": p["name"], "label": s.label(pid),
            "class": _klass(s, pid), "persona_code": p.get("persona_code")}


@router.get("/identities")
def list_identities(type: str | None = None, q: str | None = None, user: UserCtx = Depends(require_view)):
    s = engine.snapshot()
    last = {r["principal_id"]: r for r in db.query(
        "SELECT principal_id, MAX(day) AS last_day, SUM(n) AS n FROM inv_usage WHERE day >= current_date - 90 "
        "GROUP BY principal_id")}
    alerts = defaultdict(int)
    for r in db.query("SELECT principal, count(*) AS n FROM alerts WHERE status <> 'resolved' AND principal IS NOT NULL "
                      "GROUP BY principal"):
        alerts[r["principal"]] = r["n"]
    out = []
    for pid, p in s.principals.items():
        if type and p["type"] != type:
            continue
        if not p.get("in_scope") and p["type"] == "group":
            continue
        label = s.label(pid)
        if q and q.lower() not in (label + " " + p["name"]).lower():
            continue
        row = {**_brief(s, pid), "active": p.get("active"), "in_scope": p.get("in_scope"),
               "groups": len(s.groups_of(pid)), "alerts": alerts.get(pid, 0)}
        if p["type"] in ("user", "sp"):
            row["personas"] = s.personas_of(pid)
            row["readable"] = len(s.readable_tables(pid))
            u = last.get(pid)
            row["last_activity"] = str(u["last_day"]) if u else None
            row["reads_90d"] = int(u["n"]) if u else 0
        else:
            row["members"] = len(s.members.get(pid, ()))
            row["humans"] = len([m for m in s.transitive_members(pid) if s.is_human(m)])
            row["grants"] = sum(1 for rows in s.grants.values() for r in rows if r[1] == pid)
        out.append(row)
    return sorted(out, key=lambda r: r["label"].lower())


def _grant_sources(s: Snapshot, pid: str) -> list[dict]:
    ids = s.identity_set(pid)
    gr = s.groups_of(pid)
    agg: dict[tuple[str, str], dict] = {}
    for sec, rows in s.grants.items():
        for pname, ppid, priv in rows:
            if ppid not in ids:
                continue
            key = (sec, ppid)
            item = agg.setdefault(key, {
                "securable": sec, "sec_type": (s.securables.get(sec) or {}).get("type", "catalog"),
                "privileges": [], "via": _brief(s, ppid), "direct": ppid == pid,
                "path": [] if ppid == pid else gr[ppid][1], "tables": len(s.tables_under(sec)),
                "sensitivity": s.sensitivity(sec)})
            item["privileges"].append(priv)
    return sorted(agg.values(), key=lambda x: (x["securable"], x["via"]["label"]))


@router.get("/identities/{pid}")
def identity_detail(pid: str, user: UserCtx = Depends(get_user)):
    s = engine.snapshot()
    p = s.principals.get(pid)
    if not p:
        raise HTTPException(404, "identidade não encontrada no inventário")
    me_id = s.pid(user.email)
    if not user.can_view and pid != me_id:
        raise HTTPException(403, "você só pode ver o próprio acesso")
    out: dict = {"principal": {**_brief(s, pid), "active": p.get("active"), "in_scope": p.get("in_scope"),
                               "display_name": p.get("display_name")}}
    out["groups"] = sorted(
        [{**_brief(s, g), "depth": d, "path": path} for g, (d, path) in s.groups_of(pid).items()],
        key=lambda x: (x["depth"], x["label"]))
    out["alerts"] = db.query("SELECT id, rule, severity, title, object FROM alerts WHERE status <> 'resolved' "
                             "AND principal = %s ORDER BY severity", (pid,))
    if p["type"] == "group":
        tm = s.transitive_members(pid)
        out["members"] = sorted([{**_brief(s, m), "depth": d, "path": path} for m, (d, path) in tm.items()],
                                key=lambda x: (x["depth"], x["label"]))
        out["direct_grants"] = [g for g in _grant_sources(s, pid) if g["direct"]]
        mapping = db.query_one("SELECT * FROM migration_mappings WHERE legacy_group = %s", (p["name"],))
        out["mapping"] = mapping
        # concede × usa: tabelas que o grupo dá acesso vs. lidas pelos membros
        granted = set()
        for g in out["direct_grants"]:
            if any(x in g["privileges"] for x in ("SELECT", "ALL_PRIVILEGES")):
                granted |= set(s.tables_under(g["securable"]))
        humans = [m for m in tm if (s.principals.get(m) or {}).get("type") in ("user", "sp")]
        used = defaultdict(int)
        if humans:
            for r in _usage_by("principal_id = ANY(%s) AND action = 'read'", (humans,)):
                used[r["securable"]] += int(r["n"])
        out["grants_vs_use"] = sorted([{"table": t, "reads_90d": used.get(t, 0), "sensitivity": s.sensitivity(t)}
                                       for t in granted], key=lambda x: -x["reads_90d"])
        if p.get("persona_code") and p.get("group_class") == "persona":
            out["persona"] = p["persona_code"]
        return out
    out["personas"] = s.personas_of(pid)
    out["grants"] = _grant_sources(s, pid)
    readable = s.readable_tables(pid)
    usage = _usage_by("principal_id = %s", (pid,))
    reads = {r["securable"]: r for r in usage if r["action"] == "read"}
    out["readable"] = sorted([
        {"table": t, "sensitivity": s.sensitivity(t), "reads_90d": int(reads[t]["n"]) if t in reads else 0,
         "last_used": str(reads[t]["last_day"]) if t in reads else None,
         "via": next((x["via_name"] for x in s.privilege_sources(pid, t) if x["privilege"] in ("SELECT", "ALL_PRIVILEGES", "OWNER")), None)}
        for t in readable], key=lambda x: (-x["reads_90d"], x["table"]))
    out["usage"] = [{"securable": r["securable"], "action": r["action"], "n": int(r["n"]),
                     "last_day": str(r["last_day"]), "source": r["source"], "has_access": r["securable"] in readable,
                     "sensitivity": s.sensitivity(r["securable"])} for r in usage]
    out["creations"] = db.query("SELECT capability, asset_name, location, workspace_id, event_time, source "
                                "FROM inv_creations WHERE principal_id = %s ORDER BY event_time DESC LIMIT 100", (pid,))
    used_tables = {t for t in readable if t in reads}
    out["can_vs_use"] = {"readable": len(readable), "used": len(used_tables), "unused": len(readable - used_tables),
                         "sensitive_readable": sum(1 for t in readable if s.sensitivity(t))}
    out["manual_memberships"] = db.query(
        "SELECT group_name, justification, approved_by, expires_at, created_at FROM manual_members "
        "WHERE member_id = %s AND removed_at IS NULL", (pid,))
    return out


@router.get("/me/access")
def my_access(user: UserCtx = Depends(get_user)):
    s = engine.snapshot()
    pid = s.pid(user.email)
    if not pid:
        return {"in_inventory": False, "email": user.email}
    return {"in_inventory": True, "id": pid, **identity_detail(pid, user)}


@router.get("/assets")
def assets(catalog: str | None = None, user: UserCtx = Depends(require_view)):
    s = engine.snapshot()
    reads = defaultdict(int)
    readers = defaultdict(set)
    for r in db.query("SELECT securable, principal_id, SUM(n) AS n FROM inv_usage WHERE action = 'read' "
                      "AND day >= current_date - 90 GROUP BY 1, 2"):
        reads[r["securable"]] += int(r["n"])
        readers[r["securable"]].add(r["principal_id"])
    grants_n = {sec: len(rows) for sec, rows in s.grants.items()}

    def node(name: str) -> dict:
        sec = s.securables[name]
        ch = [node(c) for c in sorted(s.children.get(name, []))]
        tables = s.tables_under(name)
        return {"name": name, "label": name.split(".")[-1], "type": sec["type"], "owner": sec["owner"],
                "domain": sec.get("domain"), "sensitivity": s.sensitivity(name) if sec["type"] != "catalog" else None,
                "catalog_logical": sec.get("catalog_logical"), "grants": grants_n.get(name, 0),
                "tables": len(tables), "reads_90d": sum(reads[t] for t in tables),
                "readers_90d": len(set().union(*[readers[t] for t in tables])) if tables else 0,
                "children": ch}

    cats = [c for c in s.securables.values() if c["type"] == "catalog" and (not catalog or c["full_name"] == catalog)]
    order = {c["physical_name"]: c["sort_order"] for c in s.catalogs.values()}
    return [node(c["full_name"]) for c in sorted(cats, key=lambda c: order.get(c["full_name"], 999))]


@router.get("/assets/detail")
def asset_detail(name: str = Query(...), user: UserCtx = Depends(require_view)):
    s = engine.snapshot()
    sec = s.securables.get(name)
    if not sec:
        raise HTTPException(404, "objeto não encontrado no inventário")
    direct = defaultdict(list)
    for pname, pid, priv in s.grants.get(name, []):
        direct[pid or pname].append(priv)
    inherited = []
    for anc in s.ancestors(name)[:-1]:
        for pname, pid, priv in s.grants.get(anc, []):
            inherited.append({"securable": anc, "principal": _brief(s, pid) if pid else {"label": pname},
                              "privilege": priv})
    out = {"securable": {**sec, "sensitivity": s.sensitivity(name)},
           "direct_grants": [{"principal": _brief(s, k) if k in s.principals else {"label": k, "class": "?"},
                              "privileges": v,
                              "humans": len([m for m in s.transitive_members(k) if s.is_human(m)])
                              if (s.principals.get(k) or {}).get("type") == "group" else None}
                             for k, v in direct.items()],
           "inherited_grants": inherited}
    tables = s.tables_under(name)
    usage = _usage_by("securable = ANY(%s) AND action = 'read'", (tables,)) if tables else []
    per = defaultdict(lambda: {"n": 0, "last_day": None})
    for r in usage:
        x = per[r["principal_id"]]
        x["n"] += int(r["n"])
        x["last_day"] = max(filter(None, [x["last_day"], str(r["last_day"])]))
    out["top_users"] = sorted([{**_brief(s, k), **v} for k, v in per.items() if k in s.principals],
                              key=lambda x: -x["n"])[:30]
    if sec["type"] in ("table", "view"):
        readers = []
        dom = s.domains.get(sec.get("domain") or "")
        cl = s.pid(s.phys_group(dom["clearance_group"])) if dom and dom.get("clearance_group") else None
        for pid in s.who_can_read(name):
            src = next((x for x in s.privilege_sources(pid, name)
                        if x["privilege"] in ("SELECT", "ALL_PRIVILEGES", "OWNER")), None)
            readers.append({**_brief(s, pid), "via": src["via_name"] if src else None,
                            "granted_on": src["granted_on"] if src else None, "path": src["path"] if src else [],
                            "has_clearance": bool(cl and cl in s.groups_of(pid)),
                            "reads_90d": per.get(pid, {}).get("n", 0)})
        out["readers"] = sorted(readers, key=lambda x: (-x["reads_90d"], x["label"]))
        out["clearance_group"] = dom.get("clearance_group") if dom else None
    out["unused"] = bool(tables) and not usage
    return out


@router.get("/graph")
def graph(id: str, user: UserCtx = Depends(require_view)):
    """Rede de acessos ao redor de um nó (ego network)."""
    s = engine.snapshot()
    if id not in s.principals:
        raise HTTPException(404, "nó não encontrado")
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def add_p(pid: str, ring: int):
        if pid not in nodes:
            nodes[pid] = {"id": pid, "kind": s.principals[pid]["type"], "label": s.label(pid),
                          "class": _klass(s, pid), "ring": ring}

    add_p(id, 0)
    center = s.principals[id]
    if center["type"] == "group":
        for m in s.members.get(id, ()):
            if m in s.principals:
                add_p(m, 1)
                edges.append({"from": m, "to": id, "kind": "member"})
    for g, (d, _) in s.groups_of(id).items():
        add_p(g, d)
        for gp in [x for x, ms in s.members.items() if g in ms and x in s.groups_of(id)]:
            edges.append({"from": g, "to": gp, "kind": "member"})
        if g in s.members and id in s.members[g]:
            edges.append({"from": id, "to": g, "kind": "member"})
    ids = {id, *s.groups_of(id).keys()}
    max_ring = max([n["ring"] for n in nodes.values()] or [0])
    for sec, rows in s.grants.items():
        for _, ppid, priv in rows:
            if ppid in ids:
                key = f"sec:{sec}"
                if key not in nodes:
                    nodes[key] = {"id": key, "kind": "securable", "label": sec.split(".")[-1], "full_name": sec,
                                  "sec_type": (s.securables.get(sec) or {}).get("type", "catalog"),
                                  "sensitivity": s.sensitivity(sec), "ring": max_ring + 1}
                e = next((e for e in edges if e["from"] == ppid and e["to"] == key), None)
                if e:
                    e["privileges"].append(priv)
                else:
                    edges.append({"from": ppid, "to": key, "kind": "grant", "privileges": [priv]})
    return {"nodes": list(nodes.values()), "edges": edges}
