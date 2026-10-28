"""Inventário 360 — coleta e grava no Lakebase (espelho da UI).

Usado pelo job (SQL via Spark) e pelo app (SQL via warehouse). Coleta:
  identidades de conta (SCIM) no escopo, membros diretos (+ grupos aninhados),
  objetos do UC (catalog → schema → tabela), GRANTs diretos, tags de
  sensibilidade, uso real (table_lineage), criações (audit) e mudanças de
  permissão (audit). Dados simulados (source='demo') são preservados.
"""

from __future__ import annotations

import datetime as dt
import time
import json
from collections import defaultdict
from typing import Callable

import psycopg2.extras
from databricks.sdk import WorkspaceClient

from server import identity as idn
from server import uc
from server.engine import compute_closure

SqlFn = Callable[[str], list[dict]]


def _load_config(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT key, value FROM settings")
        settings = {k: v for k, v in cur.fetchall()}
        cur.execute("SELECT logical_name, physical_name, managed FROM catalogs")
        catalogs = [{"logical": r[0], "physical": r[1], "managed": r[2]} for r in cur.fetchall()]
        cur.execute("SELECT code, group_name, idp_group_name FROM personas")
        personas = [{"code": r[0], "group": r[1], "idp": r[2]} for r in cur.fetchall()]
        cur.execute("SELECT code, schema_name, clearance_group FROM domains")
        domains = [{"code": r[0], "schema": r[1], "clearance": r[2]} for r in cur.fetchall()]
        cur.execute("SELECT code, audit_service, audit_actions FROM capabilities")
        capabilities = [{"code": r[0], "audit_service": r[1], "audit_actions": list(r[2])} for r in cur.fetchall()]
    return {"settings": settings, "catalogs": catalogs, "personas": personas, "domains": domains,
            "capabilities": capabilities}


def classify_group(name: str, cfg: dict) -> tuple[str, str | None]:
    s = cfg["settings"]
    prefix = s.get("group_prefix") or ""
    base = name[len(prefix):] if prefix and name.startswith(prefix) else name
    for p in cfg["personas"]:
        if base == p["group"]:
            return "persona", p["code"]
        if p["idp"] and base == p["idp"]:
            return "idp_persona", p["code"]
    clearances = {d["clearance"] for d in cfg["domains"] if d["clearance"]}
    if base.startswith("clearance-") or base in clearances:
        return "clearance", None
    if (s.get("clone_group_pattern") or "users-clone") in base:
        return "clone", None
    if base in (s.get("system_groups") or []):
        return "system", None
    if prefix and not name.startswith(prefix):
        return "other", None
    return "legacy", None


def collect_identities(w: WorkspaceClient, cfg: dict) -> tuple[dict, dict]:
    """principals {id: row} e members {group_id: set(member_id)}."""
    flt = cfg["settings"].get("group_scope_filter") or None
    principals: dict[str, dict] = {}
    members: dict[str, set[str]] = defaultdict(set)
    # a listagem de conta não traz `members` — lê cada grupo
    pending_groups: list[tuple[dict, bool]] = [(idn.get_group(w, g["id"]), True) for g in idn.list_groups(w, flt)]
    seen_groups: set[str] = set()
    users, sps = set(), set()
    while pending_groups:
        g, in_scope = pending_groups.pop()
        if g["id"] in seen_groups:
            continue
        seen_groups.add(g["id"])
        cls, code = classify_group(g["displayName"], cfg)
        principals[g["id"]] = {"id": g["id"], "type": "group", "name": g["displayName"],
                               "display_name": g["displayName"], "active": True,
                               "group_class": cls if in_scope else "other", "persona_code": code,
                               "in_scope": in_scope}
        for m in g.get("members") or []:
            mt = idn.member_type(m.get("$ref"))
            members[g["id"]].add(m["value"])
            if mt == "group" and m["value"] not in seen_groups:
                try:
                    pending_groups.append((idn.get_group(w, m["value"]), in_scope))
                except Exception:  # noqa: BLE001
                    pass
            elif mt == "sp":
                sps.add(m["value"])
            elif mt == "user":
                users.add(m["value"])
    for uid in users:
        try:
            u = idn.get_user(w, uid)
        except Exception:  # noqa: BLE001
            continue
        principals[uid] = {"id": uid, "type": "user", "name": u.get("userName"), "display_name": u.get("displayName"),
                           "active": u.get("active", True), "group_class": None, "persona_code": None,
                           "in_scope": True}
    for sid in sps:
        try:
            sp = idn.get_sp(w, sid)
        except Exception:  # noqa: BLE001
            continue
        principals[sid] = {"id": sid, "type": "sp", "name": sp.get("applicationId"),
                           "display_name": sp.get("displayName"), "active": sp.get("active", True),
                           "group_class": None, "persona_code": None, "in_scope": True}
    return principals, members


def resolve_principal(w: WorkspaceClient, name: str, principals: dict, by_name: dict, cfg: dict) -> str | None:
    """Resolve um nome do UC (grupo, e-mail ou applicationId) para id SCIM."""
    key = name.lower()
    if key in by_name:
        return by_name[key]
    found = None
    try:
        if "@" in name:
            u = idn.find_user(w, name)
            if u:
                found = {"id": u["id"], "type": "user", "name": u["userName"], "display_name": u.get("displayName"),
                         "active": u.get("active", True)}
        elif len(name) == 36 and name.count("-") == 4:
            sp = idn.find_sp(w, name)
            if sp:
                found = {"id": sp["id"], "type": "sp", "name": sp["applicationId"],
                         "display_name": sp.get("displayName"), "active": sp.get("active", True)}
        if not found:
            g = idn.find_group(w, name)
            if g:
                cls, code = classify_group(g["displayName"], cfg)
                found = {"id": g["id"], "type": "group", "name": g["displayName"], "display_name": g["displayName"],
                         "active": True, "group_class": "other" if cls == "legacy" and not
                         (cfg["settings"].get("group_prefix") and name.startswith(cfg["settings"]["group_prefix"]))
                         else cls, "persona_code": code}
    except Exception:  # noqa: BLE001
        found = None
    if not found:
        return None
    found.setdefault("group_class", None)
    found.setdefault("persona_code", None)
    found["in_scope"] = False
    principals[found["id"]] = found
    by_name[key] = found["id"]
    return found["id"]


def collect_securables(w: WorkspaceClient, cfg: dict) -> tuple[list[dict], list[dict]]:
    """Objetos e GRANTs diretos dos catalogs no escopo (exceto 'system')."""
    sec: list[dict] = []
    grants: list[dict] = []
    schema_domain = {d["schema"]: d["code"] for d in cfg["domains"]}
    prd = next((c["physical"] for c in cfg["catalogs"] if c["logical"] == "data_products_prd"), None)

    def add_grants(sec_type: str, full: str):
        try:
            for a in uc.get_grants(w, sec_type, full):
                for p in a["privileges"]:
                    grants.append({"securable": full, "sec_type": sec_type, "principal": a["principal"], "privilege": p})
        except Exception as ex:  # noqa: BLE001
            print(f"[inventory] grants {full}: {ex}")

    for c in cfg["catalogs"]:
        if c["logical"] == "system":
            continue
        cat = uc.get_catalog(w, c["physical"])
        if not cat:
            continue
        sec.append({"full_name": cat["name"], "type": "catalog", "catalog": cat["name"], "schema_name": None,
                    "table_name": None, "catalog_logical": c["logical"], "domain": None, "owner": cat["owner"],
                    "created_by": cat["created_by"], "created_at": _ts(cat["created_at"])})
        add_grants("catalog", cat["name"])
        for s in uc.list_schemas(w, cat["name"]):
            domain = schema_domain.get(s["name"]) if cat["name"] == prd else None
            sec.append({"full_name": s["full_name"], "type": "schema", "catalog": cat["name"], "schema_name": s["name"],
                        "table_name": None, "catalog_logical": c["logical"], "domain": domain, "owner": s["owner"],
                        "created_by": s["created_by"], "created_at": _ts(s["created_at"])})
            add_grants("schema", s["full_name"])
            for t in uc.list_tables(w, cat["name"], s["name"]):
                sec.append({"full_name": t["full_name"], "type": t["type"], "catalog": cat["name"],
                            "schema_name": s["name"], "table_name": t["name"], "catalog_logical": c["logical"],
                            "domain": domain, "owner": t["owner"], "created_by": t["created_by"],
                            "created_at": _ts(t["created_at"])})
                add_grants("table", t["full_name"])
    return sec, grants


def _ts(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return dt.datetime.fromtimestamp(v / 1000, tz=dt.timezone.utc)
    return v


def _in_list(values) -> str:
    return ",".join("'" + str(v).replace("'", "''") + "'" for v in values) or "''"


def collect_tags(sql: SqlFn, cfg: dict) -> dict[str, str]:
    key = cfg["settings"].get("sensitivity_tag_key") or "data_sensitivity"
    cats = [c["physical"] for c in cfg["catalogs"] if c["logical"] != "system"]
    try:
        rows = sql(
            "SELECT catalog_name, schema_name, table_name, tag_value FROM system.information_schema.table_tags "
            f"WHERE catalog_name IN ({_in_list(cats)}) AND tag_name = '{key}'")
    except Exception as ex:  # noqa: BLE001
        print(f"[inventory] tags indisponíveis: {ex}")
        return {}
    return {f"{r['catalog_name']}.{r['schema_name']}.{r['table_name']}": r["tag_value"] for r in rows}


def collect_usage(sql: SqlFn, cfg: dict, days: int = 90) -> list[dict]:
    cats = [c["physical"] for c in cfg["catalogs"] if c["logical"] != "system"]
    try:
        return sql(f"""
            SELECT CAST(event_date AS STRING) AS day, created_by AS principal, source_table_full_name AS securable,
                   'read' AS action, COUNT(*) AS n
            FROM system.access.table_lineage
            WHERE event_date >= current_date() - INTERVAL {days} DAYS
              AND source_table_catalog IN ({_in_list(cats)}) AND source_table_full_name IS NOT NULL
            GROUP BY 1, 2, 3
            UNION ALL
            SELECT CAST(event_date AS STRING), created_by, target_table_full_name, 'write', COUNT(*)
            FROM system.access.table_lineage
            WHERE event_date >= current_date() - INTERVAL {days} DAYS
              AND target_table_catalog IN ({_in_list(cats)}) AND target_table_full_name IS NOT NULL
            GROUP BY 1, 2, 3""")
    except Exception as ex:  # noqa: BLE001
        print(f"[inventory] lineage indisponível: {ex}")
        return []


def collect_audit(sql: SqlFn, cfg: dict, names: list[str], capabilities: list[dict]) -> tuple[list[dict], list[dict]]:
    """Uma leitura só do audit (conta inteira = volumoso): criações de assets pelos
    principals no escopo + mudanças de permissão nos catalogs do escopo.
    Janela curta e configurável (settings.audit_lookback_days)."""
    days = int(cfg["settings"].get("audit_lookback_days") or 7)
    cats = [c["physical"] for c in cfg["catalogs"] if c["logical"] != "system"]
    likes = " OR ".join(f"request_params['securable_full_name'] LIKE '{c}%'" for c in cats) or "false"
    pairs = [(c["audit_service"], a) for c in capabilities for a in c["audit_actions"]]
    create_pred = " OR ".join(f"(service_name = '{s}' AND action_name = '{a}')" for s, a in pairs) or "false"
    if not names:
        names = ["-"]
    try:
        rows = sql(f"""
            SELECT CAST(event_time AS STRING) AS event_time, user_identity.email AS principal, service_name,
                   action_name, CAST(workspace_id AS STRING) AS workspace_id, request_id,
                   COALESCE(request_params['name'], request_params['display_name']) AS asset_name,
                   request_params['securable_full_name'] AS securable, request_params['changes'] AS changes
            FROM system.access.audit
            WHERE event_date >= current_date() - INTERVAL {days} DAYS
              AND (
                    (user_identity.email IN ({_in_list(names)}) AND ({create_pred}))
                 OR (service_name = 'unityCatalog' AND action_name = 'updatePermissions' AND ({likes}))
              )""")
    except Exception as ex:  # noqa: BLE001
        print(f"[inventory] audit indisponível: {ex}")
        return [], []
    cap_of = {(s, a): c["code"] for c in capabilities for s, a in [(c["audit_service"], x) for x in c["audit_actions"]]}
    creations, perms = [], []
    for r in rows:
        if r["service_name"] == "unityCatalog" and r["action_name"] == "updatePermissions":
            perms.append({"event_time": r["event_time"], "actor": r["principal"], "securable": r["securable"],
                          "changes": r["changes"]})
        else:
            cap = cap_of.get((r["service_name"], r["action_name"]))
            if cap:
                creations.append({"event_time": r["event_time"], "principal": r["principal"], "capability": cap,
                                  "workspace_id": r["workspace_id"], "asset_id": r["request_id"],
                                  "asset_name": r["asset_name"]})
    return creations, perms


def _grantees(changes: str | None) -> list[str]:
    try:
        return [c.get("principal") for c in json.loads(changes or "[]") if c.get("principal")]
    except Exception:  # noqa: BLE001
        return []


def run_inventory(w: WorkspaceClient, sql: SqlFn, conn) -> dict:
    """Coleta tudo e regrava o espelho no Lakebase. Retorna o inventário (p/ Delta)."""
    t0 = time.time()

    def lap(step: str):
        print(f"[inventory] {step}: {time.time() - t0:.1f}s")

    cfg = _load_config(conn)
    principals, members = collect_identities(w, cfg)
    lap("identidades")
    by_name = {p["name"].lower(): pid for pid, p in principals.items() if p.get("name")}
    secs, grants = collect_securables(w, cfg)
    lap("objetos e GRANTs")
    tags = collect_tags(sql, cfg)
    lap("tags")
    for s in secs:
        s["sensitivity"] = tags.get(s["full_name"])
    for g in grants:
        g["principal_id"] = resolve_principal(w, g["principal"], principals, by_name, cfg)
    for s in secs:
        if s.get("owner"):
            resolve_principal(w, s["owner"], principals, by_name, cfg)
    closure = compute_closure(members, principals)
    lap("resolução de principals")

    usage = []
    for r in collect_usage(sql, cfg):
        pid = by_name.get((r["principal"] or "").lower())
        if pid:
            usage.append({**r, "principal_id": pid})
    lap("uso (lineage)")
    names = [p["name"] for p in principals.values() if p["type"] == "user"]
    raw_creations, raw_perms = collect_audit(sql, cfg, names, cfg["capabilities"])
    creations = []
    for r in raw_creations:
        pid = by_name.get((r["principal"] or "").lower())
        if pid:
            creations.append({**r, "principal_id": pid})
    perm_events = []
    for r in raw_perms:
        for grantee in _grantees(r.get("changes")) or [None]:
            perm_events.append({**r, "grantee": grantee})
    lap("audit (criações e permissões)")

    write_lakebase(conn, principals, members, closure, secs, grants, usage, creations, perm_events)
    return {"principals": list(principals.values()), "members": members, "closure": closure,
            "securables": secs, "grants": grants, "usage": usage, "creations": creations,
            "permission_events": perm_events}


def write_lakebase(conn, principals, members, closure, secs, grants, usage, creations, perm_events) -> None:
    with conn.cursor() as cur:
        for t in ("inv_closure", "inv_memberships", "inv_grants", "inv_securables", "inv_principals"):
            cur.execute(f"DELETE FROM {t}")
        psycopg2.extras.execute_values(
            cur, "INSERT INTO inv_principals (id, type, name, display_name, active, group_class, persona_code, in_scope) "
                 "VALUES %s ON CONFLICT (id) DO NOTHING",
            [(p["id"], p["type"], p["name"] or p["id"], p.get("display_name"), p.get("active"), p.get("group_class"),
              p.get("persona_code"), p.get("in_scope", True)) for p in principals.values()])
        psycopg2.extras.execute_values(
            cur, "INSERT INTO inv_memberships (group_id, member_id) VALUES %s ON CONFLICT DO NOTHING",
            [(g, m) for g, ms in members.items() for m in ms] or [("", "")])
        cur.execute("DELETE FROM inv_memberships WHERE group_id = ''")
        rows = [(m, g, d, path) for m, gs in closure.items() for g, (d, path) in gs.items()]
        if rows:
            psycopg2.extras.execute_values(
                cur, "INSERT INTO inv_closure (member_id, group_id, depth, path) VALUES %s ON CONFLICT DO NOTHING", rows)
        if secs:
            psycopg2.extras.execute_values(
                cur, "INSERT INTO inv_securables (full_name, type, catalog, schema_name, table_name, catalog_logical, "
                     "domain, owner, created_by, created_at, sensitivity) VALUES %s ON CONFLICT DO NOTHING",
                [(s["full_name"], s["type"], s["catalog"], s["schema_name"], s["table_name"], s["catalog_logical"],
                  s["domain"], s["owner"], s["created_by"], s["created_at"], s.get("sensitivity")) for s in secs])
        if grants:
            psycopg2.extras.execute_values(
                cur, "INSERT INTO inv_grants (securable, sec_type, principal, principal_id, privilege) VALUES %s "
                     "ON CONFLICT DO NOTHING",
                [(g["securable"], g["sec_type"], g["principal"], g["principal_id"], g["privilege"]) for g in grants])
        cur.execute("DELETE FROM inv_usage WHERE source = 'real'")
        if usage:
            psycopg2.extras.execute_values(
                cur, "INSERT INTO inv_usage (day, principal_id, securable, action, n, source) VALUES %s "
                     "ON CONFLICT DO NOTHING",
                [(u["day"], u["principal_id"], u["securable"], u["action"], int(u["n"]), "real") for u in usage])
        cur.execute("DELETE FROM inv_creations WHERE source = 'real'")
        if creations:
            psycopg2.extras.execute_values(
                cur, "INSERT INTO inv_creations (event_time, principal_id, capability, workspace_id, asset_id, "
                     "asset_name, source) VALUES %s",
                [(c["event_time"], c["principal_id"], c["capability"], c.get("workspace_id"), c.get("asset_id"),
                  c.get("asset_name"), "real") for c in creations])
        cur.execute("DELETE FROM inv_permission_events WHERE source = 'real'")
        if perm_events:
            psycopg2.extras.execute_values(
                cur, "INSERT INTO inv_permission_events (event_time, actor, securable, grantee, detail, source) VALUES %s",
                [(e["event_time"], e["actor"], e.get("securable"), e.get("grantee"),
                  json.dumps({"changes": e.get("changes")}), "real") for e in perm_events])
        counts = {"principals": len(principals), "users": sum(1 for p in principals.values() if p["type"] == "user"),
                  "sps": sum(1 for p in principals.values() if p["type"] == "sp"),
                  "groups": sum(1 for p in principals.values() if p["type"] == "group"),
                  "securables": len(secs), "grants": len(grants), "usage_rows": len(usage)}
        cur.execute("UPDATE inv_state SET last_run_at = now(), status = 'ok', error = NULL, counts = %s WHERE id = 1",
                    (json.dumps(counts),))
    conn.commit()


def refresh_targets(w: WorkspaceClient, conn, securables: list[tuple[str, str]], group_ids: list[str]) -> None:
    """Atualização pontual após o app aplicar algo: GRANTs dos objetos e membros dos grupos tocados."""
    with conn.cursor() as cur:
        cur.execute("SELECT lower(name), id FROM inv_principals")
        by_name = dict(cur.fetchall())
        for sec_type, full in securables:
            cur.execute("DELETE FROM inv_grants WHERE securable = %s", (full,))
            for a in uc.get_grants(w, sec_type, full):
                for p in a["privileges"]:
                    cur.execute("INSERT INTO inv_grants (securable, sec_type, principal, principal_id, privilege) "
                                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                (full, sec_type, a["principal"], by_name.get(a["principal"].lower()), p))
        for gid in group_ids:
            g = idn.get_group(w, gid)
            cur.execute("DELETE FROM inv_memberships WHERE group_id = %s", (gid,))
            for m in g.get("members") or []:
                cur.execute("INSERT INTO inv_memberships (group_id, member_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                            (gid, m["value"]))
        cur.execute("SELECT id, name FROM inv_principals")
        principals = {i: {"name": n} for i, n in cur.fetchall()}
        cur.execute("SELECT group_id, member_id FROM inv_memberships")
        members: dict[str, set[str]] = defaultdict(set)
        for g, m in cur.fetchall():
            members[g].add(m)
        closure = compute_closure(members, principals)
        cur.execute("DELETE FROM inv_closure")
        rows = [(m, g, d, path) for m, gs in closure.items() for g, (d, path) in gs.items()]
        if rows:
            psycopg2.extras.execute_values(
                cur, "INSERT INTO inv_closure (member_id, group_id, depth, path) VALUES %s ON CONFLICT DO NOTHING", rows)
    conn.commit()
