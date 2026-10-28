"""Diagnóstico: indicadores, matriz grupo × catalog e anomalias principais."""

from __future__ import annotations

from collections import Counter, defaultdict

from fastapi import APIRouter, Depends

from server import db, engine
from server.engine import ALL, OWNER
from server.rbac import UserCtx, require_view

router = APIRouter(prefix="/api")

LEVEL = {"none": 0, "browse": 1, "read": 2, "write": 3, "all": 4}


def _level(privs: set[str]) -> str:
    if privs & {ALL, OWNER, "MANAGE"}:
        return "all"
    if privs & {"MODIFY", "CREATE_TABLE", "CREATE_SCHEMA", "CREATE_VOLUME"}:
        return "write"
    if "SELECT" in privs:
        return "read"
    if privs:
        return "browse"
    return "none"


@router.get("/overview")
def overview(user: UserCtx = Depends(require_view)):
    s = engine.snapshot()
    state = db.query_one("SELECT last_run_at, status, error, counts FROM inv_state WHERE id = 1")
    users = [p for p in s.principals.values() if p["type"] == "user" and p.get("in_scope")]
    sps = [p for p in s.principals.values() if p["type"] == "sp"]
    groups = [p for p in s.principals.values() if p["type"] == "group" and p.get("in_scope")]
    by_class = Counter(g.get("group_class") or "other" for g in groups)
    persona_count = Counter(min(len(s.personas_of(u["id"])), 2) for u in users)
    managed = {c["physical_name"] for c in s.catalogs.values() if c["managed"]}
    app_p = {p.lower() for p in (s.settings.get("app_principals") or [])}
    total = outside = direct_user = 0
    for sec, rows in s.grants.items():
        if sec.split(".")[0] not in managed:
            continue
        for pname, pid, _ in rows:
            total += 1
            p = s.principals.get(pid or "") or {}
            if pname.lower() in app_p:
                continue
            if not (p.get("type") == "group" and p.get("group_class") in ("persona", "clearance")):
                outside += 1
            if p.get("type") == "user":
                direct_user += 1
    alerts = db.query("SELECT id, rule, severity, title, object, first_seen FROM alerts WHERE status <> 'resolved' "
                      "ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, last_seen DESC")
    sev = Counter(a["severity"] for a in alerts)
    pending = db.query_one("SELECT count(*) AS n FROM change_requests WHERE status = 'pending'")["n"]

    # matriz: principal com GRANTs diretos × catalog (nível mais forte no catalog ou abaixo)
    cats = [c for c in s.catalogs.values() if c["managed"]]
    cells: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    schema_level: dict[str, Counter] = defaultdict(Counter)
    for sec, rows in s.grants.items():
        cat = sec.split(".")[0]
        if cat not in managed:
            continue
        for pname, pid, priv in rows:
            if pname.lower() in app_p:
                continue
            key = pid or pname
            cells[key][cat].add(priv)
            if "." in sec:
                schema_level[key][cat] += 1
    matrix = []
    for key, by_cat in cells.items():
        p = s.principals.get(key) or {"type": "?", "name": key}
        row = {"id": key, "name": s.label(key), "type": p["type"],
               "class": p.get("group_class") if p["type"] == "group" else p["type"],
               "humans": len([m for m in s.transitive_members(key) if s.is_human(m)]) if p["type"] == "group" else None,
               "cells": {}}
        for c in cats:
            privs = by_cat.get(c["physical_name"], set())
            row["cells"][c["logical_name"]] = {"level": _level(privs), "privileges": sorted(privs),
                                               "schema_grants": schema_level[key][c["physical_name"]]}
        matrix.append(row)
    order = {"persona": 0, "clearance": 1, "legacy": 2, "clone": 3, "system": 4, "user": 5, "sp": 6}
    matrix.sort(key=lambda r: (order.get(r["class"] or "", 9), r["name"]))
    return {
        "inventory": state,
        "identities": {"users": len(users), "sps": len(sps), "groups": len(groups), "groups_by_class": by_class},
        "personas": {"exactly_one": persona_count.get(1, 0), "none": persona_count.get(0, 0),
                     "multiple": persona_count.get(2, 0),
                     "migrated_pct": round(100 * persona_count.get(1, 0) / len(users)) if users else 0},
        "grants": {"total": total, "outside_model": outside, "direct_user": direct_user,
                   "outside_pct": round(100 * outside / total) if total else 0},
        "alerts": {"open": len(alerts), "by_severity": sev, "top": alerts[:8]},
        "requests_pending": pending,
        "catalogs": [{"logical": c["logical_name"], "physical": c["physical_name"], "env": c["env"]} for c in cats],
        "matrix": matrix,
    }
