"""Carga do modelo de personas no Lakebase (idempotente).

Usado no primeiro start do app (mapeamento físico = lógico) e pelo setup da
demo (mapeamento para catalogs lg_* e prefixo de grupos dbdemo-).
"""

from __future__ import annotations

import json

import psycopg2.extras

from server import model_seed as M


def seed_model(conn, catalog_map: dict[str, str] | None = None,
               settings: dict | None = None, overwrite: bool = False) -> dict:
    """Grava catalogs, domínios, personas, GRANTs desejados e capacidades.

    catalog_map: lógico → físico (default: igual). overwrite=True reescreve as
    personas/GRANTs desejados (volta ao documento); False só preenche o que falta.
    """
    catalog_map = catalog_map or {}
    cfg = {**M.DEFAULT_SETTINGS, **(settings or {})}
    with conn.cursor() as cur:
        for k, v in cfg.items():
            cur.execute(
                "INSERT INTO settings (key, value, updated_by) VALUES (%s, %s, 'seed') "
                + ("ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"
                   if overwrite else "ON CONFLICT (key) DO NOTHING"),
                (k, json.dumps(v)),
            )
        for logical, layer, env, desc, managed, order in M.CATALOGS:
            physical = catalog_map.get(logical, logical)
            cur.execute(
                """INSERT INTO catalogs (logical_name, physical_name, layer, env, description, managed, sort_order)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (logical_name) DO UPDATE SET physical_name = EXCLUDED.physical_name,
                     layer = EXCLUDED.layer, env = EXCLUDED.env, description = EXCLUDED.description,
                     managed = EXCLUDED.managed, sort_order = EXCLUDED.sort_order""",
                (logical, physical, layer, env, desc, managed, order),
            )
        for code, name, schema, sens, clearance in M.DOMAINS:
            cur.execute(
                """INSERT INTO domains (code, name, schema_name, sensitivity, clearance_group)
                   VALUES (%s,%s,%s,%s,%s) ON CONFLICT (code) DO NOTHING""",
                (code, name, schema, sens, clearance),
            )
        for code, label, svc, actions, sev in M.CAPABILITIES:
            cur.execute(
                """INSERT INTO capabilities (code, label, audit_service, audit_actions, severity)
                   VALUES (%s,%s,%s,%s,%s) ON CONFLICT (code) DO NOTHING""",
                (code, label, svc, actions, sev),
            )
        for code, label, category, desc, order in M.PERSONAS:
            cur.execute("SELECT 1 FROM personas WHERE code = %s", (code,))
            exists = cur.fetchone() is not None
            if exists and not overwrite:
                continue
            cur.execute(
                """INSERT INTO personas (code, label, category, description, group_name, idp_group_name,
                                         sort_order, updated_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'seed')
                   ON CONFLICT (code) DO UPDATE SET label = EXCLUDED.label, category = EXCLUDED.category,
                     description = EXCLUDED.description, group_name = EXCLUDED.group_name,
                     idp_group_name = EXCLUDED.idp_group_name, sort_order = EXCLUDED.sort_order,
                     version = personas.version + 1, updated_by = 'seed', updated_at = now()""",
                (code, label, category, desc, M.persona_group(code), M.idp_group(code), order),
            )
            cur.execute("DELETE FROM persona_grants WHERE persona_code = %s", (code,))
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO persona_grants (persona_code, catalog_logical, schema_scope, privileges) VALUES %s",
                [(code, c, s, p) for c, s, p in M.PERSONA_GRANTS[code]],
            )
            cur.execute("DELETE FROM persona_capabilities WHERE persona_code = %s", (code,))
            if M.PERSONA_CAPABILITIES[code]:
                psycopg2.extras.execute_values(
                    cur, "INSERT INTO persona_capabilities (persona_code, capability) VALUES %s",
                    [(code, cap) for cap in M.PERSONA_CAPABILITIES[code]],
                )
            snapshot_persona(cur, code, "seed", None)
    conn.commit()
    return {"personas": len(M.PERSONAS), "catalogs": len(M.CATALOGS)}


def persona_snapshot(cur, code: str) -> dict:
    cur.execute("SELECT code, label, category, description, group_name, idp_group_name, version "
                "FROM personas WHERE code = %s", (code,))
    p = cur.fetchone()
    cols = ["code", "label", "category", "description", "group_name", "idp_group_name", "version"]
    snap = dict(zip(cols, p)) if p and not isinstance(p, dict) else dict(p or {})
    cur.execute("SELECT catalog_logical, schema_scope, privileges FROM persona_grants "
                "WHERE persona_code = %s ORDER BY catalog_logical, schema_scope NULLS FIRST", (code,))
    snap["grants"] = [
        {"catalog": r[0], "schema_scope": r[1], "privileges": list(r[2])} if not isinstance(r, dict)
        else {"catalog": r["catalog_logical"], "schema_scope": r["schema_scope"], "privileges": list(r["privileges"])}
        for r in cur.fetchall()
    ]
    cur.execute("SELECT capability FROM persona_capabilities WHERE persona_code = %s ORDER BY 1", (code,))
    snap["capabilities"] = [r[0] if not isinstance(r, dict) else r["capability"] for r in cur.fetchall()]
    return snap


def snapshot_persona(cur, code: str, actor: str, change_id: int | None) -> None:
    snap = persona_snapshot(cur, code)
    cur.execute(
        """INSERT INTO persona_versions (persona_code, version, snapshot, change_id, changed_by)
           VALUES (%s, %s, %s, %s, %s) ON CONFLICT (persona_code, version) DO NOTHING""",
        (code, snap["version"], json.dumps(snap, default=str), change_id, actor),
    )
