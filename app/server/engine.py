"""Motor de acesso: snapshot do inventário + modelo em memória.

Resolve acesso efetivo (GRANT direto + grupos aninhados + herança catalog →
schema → tabela + ownership), o caminho de cada acesso ("por quê"), o estado
desejado das personas e simulações de mudanças (prévia de impacto).

O inventário é pequeno o bastante (escopo configurado) para caber em memória;
o snapshot é cacheado e invalidado quando o app aplica algo.
"""

from __future__ import annotations

import copy
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

from server import db

READ_PRIVS = {"SELECT"}
ALL = "ALL_PRIVILEGES"
OWNER = "OWNER"


@dataclass
class Snapshot:
    principals: dict[str, dict] = field(default_factory=dict)          # id -> row
    by_name: dict[str, str] = field(default_factory=dict)              # lower(name) -> id
    members: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))  # group -> direct members
    closure: dict[str, dict[str, tuple[int, list[str]]]] = field(default_factory=dict)  # member -> group -> (depth, path)
    securables: dict[str, dict] = field(default_factory=dict)          # full_name -> row
    children: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    grants: dict[str, list[tuple[str, str | None, str]]] = field(default_factory=lambda: defaultdict(list))
    personas: dict[str, dict] = field(default_factory=dict)
    persona_grants: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))
    persona_caps: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    catalogs: dict[str, dict] = field(default_factory=dict)            # logical -> row
    phys_to_logical: dict[str, str] = field(default_factory=dict)
    domains: dict[str, dict] = field(default_factory=dict)             # code -> row
    settings: dict = field(default_factory=dict)
    loaded_at: float = 0.0

    # ----------------------------------------------------------- nomes/grupos
    @property
    def prefix(self) -> str:
        return self.settings.get("group_prefix") or ""

    def phys_group(self, base: str) -> str:
        return f"{self.prefix}{base}"

    def base_name(self, name: str) -> str:
        p = self.prefix
        return name[len(p):] if p and name.startswith(p) else name

    def pid(self, name: str | None) -> str | None:
        return self.by_name.get((name or "").lower()) if name else None

    def label(self, pid: str | None) -> str:
        p = self.principals.get(pid or "")
        if not p:
            return pid or "?"
        return p.get("display_name") or p["name"]

    def groups_of(self, pid: str) -> dict[str, tuple[int, list[str]]]:
        return self.closure.get(pid, {})

    def identity_set(self, pid: str) -> set[str]:
        return {pid, *self.groups_of(pid).keys()}

    def personas_of(self, pid: str) -> list[str]:
        """Personas efetivas (via grupo persona-*), sem duplicar."""
        out = []
        for gid in self.groups_of(pid):
            g = self.principals.get(gid) or {}
            if g.get("group_class") == "persona" and g.get("persona_code") not in out:
                out.append(g["persona_code"])
        return out

    def transitive_members(self, gid: str) -> dict[str, tuple[int, list[str]]]:
        return {m: c[gid] for m, c in self.closure.items() if gid in c}

    def is_human(self, pid: str) -> bool:
        return (self.principals.get(pid) or {}).get("type") == "user"

    # ------------------------------------------------------------- objetos
    def ancestors(self, full_name: str) -> list[str]:
        parts = full_name.split(".")
        return [".".join(parts[:i]) for i in range(1, len(parts) + 1)]

    def tables_under(self, full_name: str) -> list[str]:
        sec = self.securables.get(full_name)
        if not sec:
            return []
        if sec["type"] in ("table", "view"):
            return [full_name]
        out = []
        for ch in self.children.get(full_name, []):
            out.extend(self.tables_under(ch))
        return out

    def sensitivity(self, full_name: str) -> str | None:
        """Sensibilidade do objeto: tag na tabela ou domínio do schema."""
        sec = self.securables.get(full_name) or {}
        if sec.get("sensitivity"):
            return sec["sensitivity"]
        dom = self.domains.get(sec.get("domain") or "")
        if dom and dom["sensitivity"] != "normal":
            return dom["sensitivity"]
        return None

    # ------------------------------------------------------ acesso efetivo
    def privilege_sources(self, pid: str, full_name: str) -> list[dict]:
        """Todas as concessões que se aplicam a `pid` em `full_name` (com herança)."""
        ids = self.identity_set(pid)
        gr = self.groups_of(pid)
        out = []
        for anc in self.ancestors(full_name):
            for pname, ppid, priv in self.grants.get(anc, []):
                if ppid in ids:
                    path = [] if ppid == pid else gr[ppid][1]
                    out.append({"privilege": priv, "granted_on": anc, "via": ppid, "via_name": pname, "path": path})
            owner = (self.securables.get(anc) or {}).get("owner")
            oid = self.pid(owner)
            if oid and oid in ids:
                path = [] if oid == pid else gr[oid][1]
                out.append({"privilege": OWNER, "granted_on": anc, "via": oid, "via_name": owner, "path": path})
        return out

    @staticmethod
    def _has(privs: set[str], *want: str) -> bool:
        return bool(privs & {ALL, OWNER, *want})

    def can_read(self, pid: str, table: str) -> bool:
        parts = table.split(".")
        if len(parts) != 3:
            return False
        cat, sch = parts[0], ".".join(parts[:2])
        ids = self.identity_set(pid)

        def privs_on(name: str) -> set[str]:
            s = {p for _, ppid, p in self.grants.get(name, []) if ppid in ids}
            if self.pid((self.securables.get(name) or {}).get("owner")) in ids:
                s.add(OWNER)
            return s

        pc, ps, pt = privs_on(cat), privs_on(sch), privs_on(table)
        if self._has(pc, OWNER) or self._has(pc, ALL):
            return True
        use_cat = self._has(pc, "USE_CATALOG")
        use_sch = self._has(pc, "USE_SCHEMA") or self._has(ps, "USE_SCHEMA")
        sel = self._has(pc, "SELECT") or self._has(ps, "SELECT") or self._has(pt, "SELECT")
        return use_cat and use_sch and sel

    def readable_tables(self, pid: str) -> set[str]:
        return {t for t, s in self.securables.items() if s["type"] in ("table", "view") and self.can_read(pid, t)}

    def who_can_read(self, table: str) -> list[str]:
        """Identidades (usuários e SPs) que conseguem ler a tabela."""
        return [p for p, r in self.principals.items() if r["type"] in ("user", "sp") and self.can_read(p, table)]

    # ------------------------------------------------------ modelo desejado
    def product_schemas(self, catalog_phys: str) -> list[str]:
        """Todos os schemas de domínio existentes (exceto staging)."""
        out = []
        for s in self.children.get(catalog_phys, []):
            name = s.split(".", 1)[1]
            if name not in ("data_staging", "information_schema", "default"):
                out.append(s)
        return out

    def persona_product_schemas(self, catalog_phys: str) -> list[str]:
        """Schemas que '@product' concede às personas: só domínios CADASTRADOS e de
        sensibilidade normal. Domínios restritos/críticos vão para o clearance;
        schemas sem cadastro aparecem como alerta até alguém classificá-los."""
        normal = {d["schema_name"] for d in self.domains.values() if d["sensitivity"] == "normal"}
        return [s for s in self.product_schemas(catalog_phys) if s.split(".", 1)[1] in normal]

    def clearance_desired(self, code: str) -> list[dict]:
        """GRANTs desejados do grupo clearance-{domínio}: ler o schema do domínio."""
        d = self.domains.get(code)
        prd = (self.catalogs.get("data_products_prd") or {}).get("physical_name")
        if not d or not d.get("clearance_group") or not prd:
            return []
        return [{"sec_type": "catalog", "securable": prd, "privileges": ["USE_CATALOG"], "managed": True},
                {"sec_type": "schema", "securable": f"{prd}.{d['schema_name']}", "privileges": ["USE_SCHEMA", "SELECT"],
                 "managed": True}]

    def clearance_plan(self, code: str) -> list[dict]:
        d = self.domains.get(code) or {}
        gname = self.phys_group(d.get("clearance_group") or "")
        gid = self.pid(gname)
        if not gid:
            return []
        plan = []
        for want in self.clearance_desired(code):
            have = {p for _, ppid, p in self.grants.get(want["securable"], []) if ppid == gid}
            missing = [p for p in want["privileges"] if p not in have and ALL not in have]
            if missing:
                plan.append({"op": "grant", "sec_type": want["sec_type"], "securable": want["securable"],
                             "principal": gname, "privileges": missing})
        return plan

    def expand_persona(self, code: str, grants: list[dict] | None = None) -> list[dict]:
        """GRANTs físicos desejados da persona: [{sec_type, securable, privileges, managed}]."""
        rows = grants if grants is not None else self.persona_grants.get(code, [])
        out: dict[tuple[str, str], dict] = {}
        for g in rows:
            cat = self.catalogs.get(g["catalog"])
            if not cat:
                continue
            phys = cat["physical_name"]
            scope = g.get("schema_scope")
            if not scope:
                targets = [("catalog", phys)]
            elif scope == "@staging":
                targets = [("schema", f"{phys}.data_staging")]
            elif scope == "@product":
                targets = [("schema", s) for s in self.persona_product_schemas(phys)]
            else:
                targets = [("schema", f"{phys}.{scope}")]
            for st, sec in targets:
                key = (st, sec)
                cur = out.setdefault(key, {"sec_type": st, "securable": sec, "privileges": [],
                                           "managed": bool(cat["managed"]), "catalog_logical": g["catalog"]})
                for p in g["privileges"]:
                    if p not in cur["privileges"]:
                        cur["privileges"].append(p)
        return list(out.values())

    def persona_gap(self, code: str, grants: list[dict] | None = None) -> dict:
        """Desejado × atual dos GRANTs diretos no grupo da persona."""
        persona = self.personas[code]
        gname = self.phys_group(persona["group_name"])
        gid = self.pid(gname)
        desired = self.expand_persona(code, grants)
        desired_keys = {(d["securable"], p) for d in desired for p in d["privileges"]}
        actual = {}
        if gid:
            for sec, rows in self.grants.items():
                for _, ppid, priv in rows:
                    if ppid == gid:
                        actual[(sec, priv)] = (self.securables.get(sec) or {}).get("type", "catalog")
        items = []
        for d in desired:
            for p in d["privileges"]:
                k = (d["securable"], p)
                status = "ok" if k in actual or (d["securable"], ALL) in actual else "missing"
                if not d["managed"]:
                    status = "unmanaged" if status == "missing" else status
                items.append({"securable": d["securable"], "sec_type": d["sec_type"], "privilege": p,
                              "status": status})
        managed_phys = {c["physical_name"] for c in self.catalogs.values() if c["managed"]}
        for (sec, priv), st in actual.items():
            if (sec, priv) in desired_keys:
                continue
            if sec.split(".")[0] not in managed_phys:
                continue
            items.append({"securable": sec, "sec_type": st, "privilege": priv, "status": "extra"})
        counts = defaultdict(int)
        for i in items:
            counts[i["status"]] += 1
        return {"persona": code, "group": gname, "group_id": gid, "group_exists": bool(gid),
                "items": sorted(items, key=lambda i: (i["status"] != "missing", i["status"] != "extra",
                                                      i["securable"], i["privilege"])),
                "counts": dict(counts)}

    def gap_plan(self, code: str, grants: list[dict] | None = None) -> list[dict]:
        gap = self.persona_gap(code, grants)
        by: dict[tuple[str, str, str], list[str]] = defaultdict(list)
        for i in gap["items"]:
            if i["status"] == "missing":
                by[("grant", i["sec_type"], i["securable"])].append(i["privilege"])
            elif i["status"] == "extra":
                by[("revoke", i["sec_type"], i["securable"])].append(i["privilege"])
        return [{"op": op, "sec_type": st, "securable": sec, "principal": gap["group"], "privileges": privs}
                for (op, st, sec), privs in sorted(by.items(), key=lambda kv: (kv[0][0], kv[0][2]))]

    # --------------------------------------------------------- simulação
    def simulate(self, ops: list[dict]) -> "Snapshot":
        sim = copy.copy(self)
        sim.grants = defaultdict(list, {k: list(v) for k, v in self.grants.items()})
        sim.members = defaultdict(set, {k: set(v) for k, v in self.members.items()})
        for op in ops:
            kind = op["op"]
            if kind in ("grant", "revoke"):
                ppid = self.pid(op["principal"])
                rows = sim.grants[op["securable"]]
                for priv in op["privileges"]:
                    if kind == "grant":
                        if not any(r[1] == ppid and r[2] == priv for r in rows):
                            rows.append((op["principal"], ppid, priv))
                    else:
                        sim.grants[op["securable"]] = rows = [r for r in rows if not (r[1] == ppid and r[2] == priv)]
            elif kind == "add_member":
                sim.members[op["group_id"]].add(op["member_id"])
            elif kind == "remove_member":
                sim.members[op["group_id"]].discard(op["member_id"])
        if any(o["op"] in ("add_member", "remove_member") for o in ops):
            sim.closure = compute_closure(sim.members, self.principals)
        return sim

    def impact(self, ops: list[dict], usage_days: int = 30) -> dict:
        """Quem ganha/perde leitura de quais tabelas, cruzado com o uso real."""
        sim = self.simulate(ops)
        affected: set[str] = set()
        for op in ops:
            if op["op"] in ("grant", "revoke"):
                gid = self.pid(op["principal"])
                if gid:
                    affected.add(gid)
                    affected |= set(self.transitive_members(gid).keys())
                    affected |= set(sim.transitive_members(gid).keys())
            else:
                affected.add(op["member_id"])
                affected |= set(self.transitive_members(op["member_id"]).keys())
        affected = {a for a in affected if (self.principals.get(a) or {}).get("type") in ("user", "sp")}
        used = recent_usage(usage_days)
        people = []
        for pid in sorted(affected, key=self.label):
            before, after = self.readable_tables(pid), sim.readable_tables(pid)
            lost, gained = sorted(before - after), sorted(after - before)
            if not lost and not gained:
                continue
            used_lost = [t for t in lost if (pid, t) in used]
            people.append({"id": pid, "name": self.label(pid), "type": self.principals[pid]["type"],
                           "lost": lost, "gained": gained, "used_lost": used_lost})
        return {
            "people": people,
            "summary": {
                "affected": len(people),
                "losing": sum(1 for p in people if p["lost"]),
                "gaining": sum(1 for p in people if p["gained"]),
                "lost_tables": len({t for p in people for t in p["lost"]}),
                "gained_tables": len({t for p in people for t in p["gained"]}),
                "used_lost_people": sum(1 for p in people if p["used_lost"]),
                "usage_days": usage_days,
            },
        }


def compute_closure(members: dict[str, set[str]], principals: dict[str, dict]) -> dict:
    """member -> {group: (depth, path de nomes do membro até o grupo)}."""
    parents: dict[str, set[str]] = defaultdict(set)
    for g, ms in members.items():
        for m in ms:
            parents[m].add(g)
    name = lambda i: (principals.get(i) or {}).get("name", i)  # noqa: E731
    closure: dict[str, dict[str, tuple[int, list[str]]]] = {}
    for m in set(parents.keys()):
        seen: dict[str, tuple[int, list[str]]] = {}
        dq = deque([(g, 1, [name(g)]) for g in parents[m]])
        while dq:
            g, d, path = dq.popleft()
            if g in seen:
                continue
            seen[g] = (d, path)
            for gp in parents.get(g, ()):
                if gp not in seen:
                    dq.append((gp, d + 1, path + [name(gp)]))
        closure[m] = seen
    return closure


# ----------------------------------------------------------------- cache/IO
_lock = threading.Lock()
_cache: Snapshot | None = None
_TTL = 60.0


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None


def snapshot() -> Snapshot:
    global _cache
    with _lock:
        if _cache and time.time() - _cache.loaded_at < _TTL:
            return _cache
    snap = load()
    with _lock:
        _cache = snap
    return snap


def load() -> Snapshot:
    s = Snapshot()
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT key, value FROM settings")
            s.settings = {k: v for k, v in cur.fetchall()}
            cur.execute("SELECT id, type, name, display_name, active, group_class, persona_code, in_scope "
                        "FROM inv_principals")
            for r in cur.fetchall():
                row = dict(zip(["id", "type", "name", "display_name", "active", "group_class", "persona_code",
                                "in_scope"], r))
                s.principals[row["id"]] = row
                s.by_name[row["name"].lower()] = row["id"]
                if row["type"] == "group" and row.get("display_name"):
                    s.by_name.setdefault(row["display_name"].lower(), row["id"])
            cur.execute("SELECT group_id, member_id FROM inv_memberships")
            for g, m in cur.fetchall():
                s.members[g].add(m)
            cur.execute("SELECT member_id, group_id, depth, path FROM inv_closure")
            for m, g, d, p in cur.fetchall():
                s.closure.setdefault(m, {})[g] = (d, list(p))
            cur.execute("SELECT full_name, type, catalog, schema_name, table_name, catalog_logical, domain, owner, "
                        "created_by, created_at, sensitivity FROM inv_securables")
            for r in cur.fetchall():
                row = dict(zip(["full_name", "type", "catalog", "schema_name", "table_name", "catalog_logical",
                                "domain", "owner", "created_by", "created_at", "sensitivity"], r))
                s.securables[row["full_name"]] = row
                if row["type"] != "catalog":
                    parent = row["full_name"].rsplit(".", 1)[0]
                    s.children[parent].append(row["full_name"])
            cur.execute("SELECT securable, principal, principal_id, privilege FROM inv_grants")
            for sec, pname, ppid, priv in cur.fetchall():
                s.grants[sec].append((pname, ppid, priv))
            cur.execute("SELECT code, label, category, description, group_name, idp_group_name, version, sort_order "
                        "FROM personas ORDER BY sort_order")
            for r in cur.fetchall():
                row = dict(zip(["code", "label", "category", "description", "group_name", "idp_group_name",
                                "version", "sort_order"], r))
                s.personas[row["code"]] = row
            cur.execute("SELECT persona_code, catalog_logical, schema_scope, privileges FROM persona_grants "
                        "ORDER BY catalog_logical, schema_scope NULLS FIRST")
            for code, cat, scope, privs in cur.fetchall():
                s.persona_grants[code].append({"catalog": cat, "schema_scope": scope, "privileges": list(privs)})
            cur.execute("SELECT persona_code, capability FROM persona_capabilities")
            for code, cap in cur.fetchall():
                s.persona_caps[code].add(cap)
            cur.execute("SELECT logical_name, physical_name, layer, env, description, managed, sort_order "
                        "FROM catalogs ORDER BY sort_order")
            for r in cur.fetchall():
                row = dict(zip(["logical_name", "physical_name", "layer", "env", "description", "managed",
                                "sort_order"], r))
                s.catalogs[row["logical_name"]] = row
                s.phys_to_logical[row["physical_name"]] = row["logical_name"]
            cur.execute("SELECT code, name, schema_name, owner, sensitivity, clearance_group, description FROM domains")
            for r in cur.fetchall():
                row = dict(zip(["code", "name", "schema_name", "owner", "sensitivity", "clearance_group",
                                "description"], r))
                s.domains[row["code"]] = row
    s.loaded_at = time.time()
    return s


def recent_usage(days: int = 30) -> set[tuple[str, str]]:
    rows = db.query(
        "SELECT DISTINCT principal_id, securable FROM inv_usage "
        "WHERE action = 'read' AND day >= current_date - %s::int", (days,))
    return {(r["principal_id"], r["securable"]) for r in rows}
