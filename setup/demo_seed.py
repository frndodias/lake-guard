"""Ambiente de DEMO no fevm-fc que simula o cenário da Nuvemshop.

Cria (idempotente):
  * catalogs lg_* (raw, data_products_prd/dev, sandbox, billing, ds_*) com tabelas pequenas
  * grupos de conta dbdemo-* (personas, espelhos do IdP, clearance, legados, clone, SPs)
  * usuários fictícios dbdemo.*@nuvemshop.example (domínio que não recebe e-mail) e SPs dbdemo-sp-*
  * GRANTs propositalmente bagunçados (o "estado atual" a diagnosticar)
  * delegação: SP do app como group manager dos grupos e MANAGE nos catalogs lg_*
  * modelo de personas no Lakebase (schema lg) + uso/criações simulados

Uso:  ~/dev/lg-venv/bin/python setup/demo_seed.py [--skip-uc] [--skip-identities]
Limpeza: setup/demo_cleanup.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402
from databricks.sdk import WorkspaceClient  # noqa: E402
from databricks.sdk.service.sql import StatementState  # noqa: E402

from server import identity as idn  # noqa: E402
from server import uc  # noqa: E402
from server.seed import seed_model  # noqa: E402

PROFILE = os.environ.get("DATABRICKS_PROFILE", "fevm-fc")
WAREHOUSE = os.environ.get("WAREHOUSE_ID", "02a3a16cad439d0b")
ACCOUNT_ID = "05d08df7-ae03-43ad-bbae-14babb530ec0"
APP_SP = "0548bfe6-82db-4d5b-9a38-03c876c08a41"           # SP do app lakeguard
ME = "fernando.custodio@databricks.com"
STORAGE = "s3://fc-ext-s3-049629455384-pede07/lakeguard_demo"
PFX = "dbdemo-"
TAG = "lg_sensitivity"
LAKEBASE_INSTANCE = "lakeguard"
MANIFEST = ROOT / "setup" / "demo_manifest.json"

CATALOG_MAP = {
    "raw": "lg_raw", "data_products_prd": "lg_data_products_prd", "data_products_dev": "lg_data_products_dev",
    "sandbox": "lg_sandbox", "billing_data": "lg_billing_data", "ds_catalog": "lg_ds_catalog",
    "ds_outputs_prd": "lg_ds_outputs_prd", "ds_outputs_dev": "lg_ds_outputs_dev", "system": "system",
}
C = CATALOG_MAP

# catalog físico -> {schema: [(tabela, sensibilidade|None)]}
UC_LAYOUT = {
    C["raw"]: {"shopify": [("orders", None), ("customers", "restricted")],
               "salesforce": [("accounts", None)], "segment": [("tracks", None)],
               "hr_system": [("employees", "critical")]},
    C["data_products_prd"]: {
        "data_staging": [("orders__shopify__raw_order__event", None), ("customers__shopify__customer__event", "restricted")],
        "data_operations": [("s__orders__order__event", None), ("g__operations__orders_gmv__agg_daily", None)],
        "data_marketing": [("g__marketing__campaign__agg_daily", None), ("s__marketing__lead__event", None)],
        "data_product": [("s__product__catalog__snapshot", None)],
        "data_finance": [("g__finance__receita__agg_daily", None), ("s__finance__invoice__event", "restricted")],
        "data_fintech": [("s__fintech__loan__event", "critical")],
        "data_people": [("s__people__employee__snapshot", "critical")],
        "data_logistics": [("g__logistics__shipments__agg_daily", None)],   # schema "novo", sem GRANTs
    },
    C["data_products_dev"]: {"dev_shared": [("tmp_orders_model", None)], "dev_joana": [("wip_campaign_attr", None)]},
    C["sandbox"]: {"adhoc": [("analise_black_friday", None)]},
    C["billing_data"]: {"billing": [("invoices", "restricted"), ("usage_charges", None)]},
    C["ds_catalog"]: {"features": [("customer_features", None)]},
    C["ds_outputs_prd"]: {"churn": [("churn_scores", None)]},
    C["ds_outputs_dev"]: {"experiments": [("exp_001_results", None)]},
}

USERS = [  # (slug, nome)
    ("joana.silva", "Joana Silva"), ("pedro.santos", "Pedro Santos"), ("ana.costa", "Ana Costa"),
    ("lucas.oliveira", "Lucas Oliveira"), ("mariana.souza", "Mariana Souza"), ("rafael.lima", "Rafael Lima"),
    ("beatriz.rocha", "Beatriz Rocha"), ("carlos.mendes", "Carlos Mendes"), ("fernanda.alves", "Fernanda Alves"),
    ("gustavo.pereira", "Gustavo Pereira"), ("juliana.ribeiro", "Juliana Ribeiro"),
    ("thiago.carvalho", "Thiago Carvalho"), ("camila.gomes", "Camila Gomes"), ("bruno.martins", "Bruno Martins"),
    ("larissa.dias", "Larissa Dias"), ("rodrigo.barbosa", "Rodrigo Barbosa"), ("patricia.nunes", "Patricia Nunes"),
    ("felipe.teixeira", "Felipe Teixeira"), ("aline.moreira", "Aline Moreira"), ("diego.freitas", "Diego Freitas"),
]
INACTIVE = {"felipe.teixeira"}
SPS = ["sp-dbt-prod", "sp-airflow-ingest", "sp-tableau", "sp-cursor-agent", "sp-claude-agent", "sp-vercel-agent"]


def email(slug: str) -> str:
    return f"dbdemo.{slug}@nuvemshop.example"


# grupo (sem prefixo) -> membros: usuários (slug), "sp:<nome>", "group:<grupo sem prefixo>"
GROUPS = {
    # personas oficiais (data-engineer e data-steward vazias, como no cliente)
    **{f"persona-{p}": [] for p in ["platform-admin", "data-engineer", "analytics-engineer", "data-scientist",
                                     "mlops", "sql-explorer", "data-explorer", "data-steward", "data-observer"]},
    # espelhos do IdP (simulam grupos sincronizados via SCIM)
    "idp-persona-analytics-engineer": ["joana.silva", "pedro.santos"],
    "idp-persona-sql-explorer": ["ana.costa", "thiago.carvalho"],
    "idp-persona-data-explorer": ["fernanda.alves", "larissa.dias", "thiago.carvalho"],
    "idp-persona-data-scientist": ["mariana.souza"],
    "idp-persona-mlops": ["rafael.lima"],
    "idp-persona-platform-admin": ["carlos.mendes"],
    "idp-persona-data-observer": ["gustavo.pereira", "patricia.nunes"],
    # clearance (ainda vazios)
    "clearance-finance": [], "clearance-fintech": [], "clearance-people": [],
    # legados por área
    "finance": ["pedro.santos", "beatriz.rocha", "juliana.ribeiro"],
    "marketing": ["joana.silva", "fernanda.alves"],
    "fintech": ["juliana.ribeiro"],
    "operations": ["lucas.oliveira", "larissa.dias", "rodrigo.barbosa", "felipe.teixeira"],
    "product": ["bruno.martins"],
    "analytics-team": ["group:marketing", "ana.costa", "camila.gomes"],
    "projeto-black-friday-2024": [],
    # clone automático do grupo users
    "users-clone-2026-08-05-1647-UTC": [u for u, _ in USERS],
    # agentes / SPs
    "Service-Principals": [f"sp:{s}" for s in SPS],
    "mcp-cursor-group": ["sp:sp-cursor-agent"],
}

R, U, S = ["USE_CATALOG", "USE_SCHEMA", "SELECT"], ["USE_CATALOG"], ["USE_SCHEMA", "SELECT"]
# GRANTs do estado ATUAL (bagunçado). principal: grupo sem prefixo | "user:<slug>" | "sp:<nome>"
GRANTS = [
    # clone: todo mundo lê tudo em produção
    ("catalog", C["data_products_prd"], "users-clone-2026-08-05-1647-UTC", R),
    ("catalog", C["raw"], "users-clone-2026-08-05-1647-UTC", ["BROWSE"]),
    # legados
    ("catalog", C["billing_data"], "finance", ["ALL_PRIVILEGES"]),
    ("catalog", C["data_products_prd"], "finance", U),
    ("schema", f"{C['data_products_prd']}.data_finance", "finance", S),
    ("catalog", C["data_products_prd"], "marketing", R),
    ("catalog", C["sandbox"], "marketing", ["USE_CATALOG", "USE_SCHEMA", "CREATE_TABLE"]),
    ("catalog", C["data_products_prd"], "fintech", U),
    ("schema", f"{C['data_products_prd']}.data_fintech", "fintech", ["USE_SCHEMA", "SELECT", "MODIFY"]),
    ("catalog", C["raw"], "operations", ["USE_CATALOG", "USE_SCHEMA", "SELECT", "MODIFY"]),
    ("catalog", C["data_products_prd"], "operations", U),
    ("schema", f"{C['data_products_prd']}.data_operations", "operations", S),
    ("catalog", C["data_products_dev"], "operations", ["USE_CATALOG", "USE_SCHEMA", "CREATE_TABLE"]),
    ("catalog", C["data_products_prd"], "product", U),
    ("schema", f"{C['data_products_prd']}.data_product", "product", S),
    ("schema", f"{C['data_products_prd']}.data_staging", "analytics-team", S),
    ("schema", f"{C['data_products_prd']}.data_marketing", "analytics-team", S),
    ("catalog", C["sandbox"], "analytics-team", ["USE_CATALOG", "USE_SCHEMA", "CREATE_TABLE"]),
    ("schema", f"{C['data_products_prd']}.data_marketing", "projeto-black-friday-2024", S),
    # agentes
    ("catalog", C["data_products_prd"], "Service-Principals", ["ALL_PRIVILEGES"]),
    ("catalog", C["raw"], "Service-Principals", ["USE_CATALOG", "USE_SCHEMA", "SELECT", "MODIFY"]),
    ("catalog", C["data_products_prd"], "mcp-cursor-group", R),
    # pipeline SP direto (escreve em produção)
    ("catalog", C["data_products_prd"], "sp:sp-dbt-prod", ["USE_CATALOG", "USE_SCHEMA", "SELECT", "MODIFY"]),
    # GRANTs diretos a usuário
    ("table", f"{C['data_products_prd']}.data_people.s__people__employee__snapshot", "user:diego.freitas", ["SELECT"]),
    ("schema", f"{C['data_products_prd']}.data_people", "user:diego.freitas", ["USE_SCHEMA"]),
    ("table", f"{C['billing_data']}.billing.invoices", "user:juliana.ribeiro", ["SELECT", "MODIFY"]),
    # personas — adoção parcial
    ("catalog", C["data_products_prd"], "persona-analytics-engineer", R),
    ("catalog", C["data_products_prd"], "persona-sql-explorer", ["USE_CATALOG"]),
    ("schema", f"{C['data_products_prd']}.data_staging", "persona-sql-explorer", S),
    ("catalog", C["raw"], "persona-sql-explorer", R),                       # extra (fora do modelo)
    ("catalog", C["data_products_prd"], "persona-data-explorer", ["USE_CATALOG", "BROWSE"]),
    ("catalog", C["data_products_prd"], "persona-data-scientist", R),
    ("catalog", C["raw"], "persona-data-scientist", R),
    ("catalog", C["ds_catalog"], "persona-data-scientist", ["USE_CATALOG", "USE_SCHEMA", "CREATE_TABLE"]),
    ("catalog", C["data_products_prd"], "persona-data-observer", ["BROWSE"]),
    *[("catalog", C[c], "persona-platform-admin", ["ALL_PRIVILEGES"])
      for c in ["data_products_prd", "data_products_dev", "raw", "sandbox", "billing_data",
                "ds_catalog", "ds_outputs_prd", "ds_outputs_dev"]],
]


# --------------------------------------------------------------------------- #
def sql_runner(w: WorkspaceClient):
    def run(stmt: str) -> list[dict]:
        r = w.statement_execution.execute_statement(statement=stmt, warehouse_id=WAREHOUSE, wait_timeout="50s")
        while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(1)
            r = w.statement_execution.get_statement(r.statement_id)
        if r.status.state != StatementState.SUCCEEDED:
            raise RuntimeError(f"{r.status.error.message if r.status.error else r.status.state}: {stmt[:160]}")
        if not r.manifest or not r.result or not r.result.data_array:
            return []
        cols = [c.name for c in r.manifest.schema.columns]
        return [dict(zip(cols, row)) for row in r.result.data_array]
    return run


def setup_uc(w: WorkspaceClient) -> None:
    run = sql_runner(w)
    existing = {c.name for c in w.catalogs.list()}
    for cat, schemas in UC_LAYOUT.items():
        if cat not in existing:
            w.catalogs.create(name=cat, storage_root=f"{STORAGE}/{cat}",
                              comment="Lakeguard demo (simula catalog da Nuvemshop)")
            print(f"  catalog {cat} criado")
        for sch, tables in schemas.items():
            run(f"CREATE SCHEMA IF NOT EXISTS {uc.q(cat + '.' + sch)}")
            for tbl, sens in tables:
                fq = uc.q(f"{cat}.{sch}.{tbl}")
                run(f"CREATE TABLE IF NOT EXISTS {fq} AS SELECT * FROM VALUES "
                    f"(1, 'a', current_date()), (2, 'b', current_date()) AS t(id, valor, dt)")
                if sens:
                    run(f"ALTER TABLE {fq} SET TAGS ('{TAG}' = '{sens}')")
    print("  UC pronto")


def ensure_identities(w: WorkspaceClient) -> dict:
    ids: dict = {"users": {}, "sps": {}, "groups": {}}
    for slug, name in USERS:
        u = idn.find_user(w, email(slug)) or idn.create_user(w, email(slug), f"{name} (demo)")
        ids["users"][slug] = {"id": u["id"], "userName": email(slug)}
        if slug in INACTIVE and u.get("active", True):
            try:  # desativar exige account admin — best-effort
                idn.set_user_active(w, u["id"], False)
            except Exception:  # noqa: BLE001
                pass
    for sp in SPS:
        name = PFX + sp
        s = idn.find_sp_by_name(w, name) or idn.create_sp(w, name)
        ids["sps"][sp] = {"id": s["id"], "applicationId": s["applicationId"], "displayName": name}
    for g in GROUPS:
        name = PFX + g
        grp = idn.find_group(w, name) or idn.create_group(w, name)
        ids["groups"][g] = {"id": grp["id"], "displayName": name}
    # membros
    for g, members in GROUPS.items():
        gid = ids["groups"][g]["id"]
        current = {m["value"] for m in (idn.get_group(w, gid).get("members") or [])}
        for m in members:
            if m.startswith("sp:"):
                mid = ids["sps"][m[3:]]["id"]
            elif m.startswith("group:"):
                mid = ids["groups"][m[6:]]["id"]
            else:
                mid = ids["users"][m]["id"]
            if mid not in current:
                idn.add_member(w, gid, mid)
    # aninhamento IdP → persona
    for g in GROUPS:
        if g.startswith("idp-persona-"):
            persona = "persona-" + g[len("idp-persona-"):]
            pid = ids["groups"][persona]["id"]
            current = {m["value"] for m in (idn.get_group(w, pid).get("members") or [])}
            if ids["groups"][g]["id"] not in current:
                idn.add_member(w, pid, ids["groups"][g]["id"])
    # delegação: SP do app gerencia membros dos grupos
    for g in ids["groups"].values():
        idn.add_group_managers(w, ACCOUNT_ID, g["id"], [f"users/{ME}", f"servicePrincipals/{APP_SP}"])
    print(f"  identidades: {len(ids['users'])} usuários, {len(ids['sps'])} SPs, {len(ids['groups'])} grupos")
    return ids


def principal_name(ids: dict, p: str) -> str:
    if p.startswith("user:"):
        return ids["users"][p[5:]]["userName"]
    if p.startswith("sp:"):
        return ids["sps"][p[3:]]["applicationId"]
    return PFX + p


def apply_grants(w: WorkspaceClient, ids: dict) -> None:
    for sec_type, full, p, privs in GRANTS:
        uc.update_grants(w, sec_type, full, principal_name(ids, p), add=privs)
    for cat in UC_LAYOUT:
        uc.update_grants(w, "catalog", cat, APP_SP, add=["USE_CATALOG", "USE_SCHEMA", "BROWSE", "MANAGE"])
    print(f"  {len(GRANTS)} GRANTs do estado atual + MANAGE do SP do app")


# --------------------------------------------------------------------------- #
def lakebase_conn(w: WorkspaceClient):
    inst = w.database.get_database_instance(name=LAKEBASE_INSTANCE)
    cred = w.database.generate_database_credential(instance_names=[LAKEBASE_INSTANCE])
    conn = psycopg2.connect(host=inst.read_write_dns, port=5432, dbname="lakeguard", user=ME,
                            password=cred.token, sslmode="require", connect_timeout=15)
    with conn.cursor() as cur:
        cur.execute("SET search_path TO lg, public")
    conn.commit()
    return conn


# uso simulado: quem lê o quê (padrões coerentes com o papel de cada um)
P = C["data_products_prd"]
USAGE_PROFILE = {
    "joana.silva": [f"{P}.data_marketing.g__marketing__campaign__agg_daily", f"{P}.data_staging.orders__shopify__raw_order__event",
                    f"{C['raw']}.segment.tracks"],
    "pedro.santos": [f"{P}.data_finance.g__finance__receita__agg_daily", f"{C['billing_data']}.billing.usage_charges"],
    "ana.costa": [f"{P}.data_operations.g__operations__orders_gmv__agg_daily", f"{P}.data_staging.orders__shopify__raw_order__event"],
    "lucas.oliveira": [f"{C['raw']}.shopify.orders", f"{P}.data_operations.s__orders__order__event"],
    "mariana.souza": [f"{C['ds_catalog']}.features.customer_features", f"{P}.data_operations.s__orders__order__event"],
    "rafael.lima": [f"{C['ds_outputs_prd']}.churn.churn_scores"],
    "beatriz.rocha": [f"{P}.data_finance.g__finance__receita__agg_daily", f"{P}.data_finance.s__finance__invoice__event"],
    "fernanda.alves": [f"{P}.data_marketing.g__marketing__campaign__agg_daily"],
    "juliana.ribeiro": [f"{P}.data_fintech.s__fintech__loan__event", f"{C['billing_data']}.billing.invoices"],
    "thiago.carvalho": [f"{P}.data_product.s__product__catalog__snapshot"],
    "camila.gomes": [f"{P}.data_marketing.s__marketing__lead__event"],
    "bruno.martins": [f"{P}.data_product.s__product__catalog__snapshot"],
    "larissa.dias": [f"{P}.data_operations.g__operations__orders_gmv__agg_daily"],
    "rodrigo.barbosa": [f"{C['raw']}.shopify.orders"],
    "diego.freitas": [f"{P}.data_people.s__people__employee__snapshot"],
    "aline.moreira": [f"{P}.data_marketing.g__marketing__campaign__agg_daily"],
    "sp:sp-dbt-prod": [f"{P}.data_operations.s__orders__order__event", f"{P}.data_staging.orders__shopify__raw_order__event"],
    "sp:sp-tableau": [f"{P}.data_operations.g__operations__orders_gmv__agg_daily", f"{P}.data_finance.g__finance__receita__agg_daily"],
    "sp:sp-cursor-agent": [f"{P}.data_operations.s__orders__order__event", f"{P}.data_finance.s__finance__invoice__event",
                           f"{P}.data_people.s__people__employee__snapshot", f"{P}.data_marketing.s__marketing__lead__event"],
    "sp:sp-claude-agent": [f"{P}.data_product.s__product__catalog__snapshot"],
}
WRITES = {"sp:sp-dbt-prod": [f"{P}.data_operations.s__orders__order__event"],
          "sp:sp-airflow-ingest": [f"{C['raw']}.shopify.orders", f"{C['raw']}.segment.tracks"],
          "juliana.ribeiro": [f"{C['billing_data']}.billing.invoices"]}

CREATIONS = [  # (quem, capacidade, nome, local)
    ("joana.silva", "dashboard", "Campanhas — performance diária", f"{P}.data_marketing"),
    ("joana.silva", "dashboard", "Funil de aquisição", f"{P}.data_marketing"),
    ("joana.silva", "genie", "Genie Marketing", f"{P}.data_marketing"),
    ("pedro.santos", "dashboard", "Receita diária", f"{P}.data_finance"),
    ("ana.costa", "job", "export_gmv_diario", f"{P}.data_operations"),            # sql-explorer não cria job
    ("fernanda.alves", "genie", "Genie campanhas (pessoal)", f"{P}.data_marketing"),  # explorer não cria
    ("lucas.oliveira", "cluster", "cluster-lucas-adhoc", "compute"),                # sem persona
    ("mariana.souza", "notebook", "churn_feature_eng", "/Users/mariana"),
    ("rafael.lima", "model_serving", "churn-endpoint", "serving"),
    ("sp:sp-cursor-agent", "dashboard", "Resumo gerado pelo Cursor", f"{P}.data_operations"),
    ("sp:sp-vercel-agent", "app", "storefront-insights", "apps"),
]


def seed_lakebase(w: WorkspaceClient, ids: dict) -> None:
    conn = lakebase_conn(w)
    seed_model(conn, catalog_map=CATALOG_MAP, overwrite=True, settings={
        "group_prefix": PFX,
        "group_scope_filter": f'displayName sw "{PFX}"',
        "sensitivity_tag_key": TAG,
        "demo_mode": True,
        "allow_self_approval": True,
        "system_groups": ["Service-Principals", "mcp-cursor-group"],
        "app_principals": [APP_SP],
    })
    with conn.cursor() as cur:
        for role, dom in [("admin", None), ("dpo", None)] + [("steward", d) for d in
                                                             ["finance", "fintech", "people", "marketing",
                                                              "operations", "product"]]:
            cur.execute("""INSERT INTO app_roles (principal, principal_type, role, domain, granted_by)
                           VALUES (%s,'user',%s,%s,'seed') ON CONFLICT DO NOTHING""", (ME, role, dom))
        cur.execute("UPDATE domains SET owner = %s WHERE code = 'finance'", (email("beatriz.rocha"),))
        # uso simulado (90 dias)
        rnd = random.Random(42)
        today = dt.date.today()

        def pid(who: str) -> str:
            return ids["sps"][who[3:]]["id"] if who.startswith("sp:") else ids["users"][who]["id"]

        rows = []
        for who, tables in USAGE_PROFILE.items():
            for d in range(90):
                day = today - dt.timedelta(days=d)
                if day.weekday() >= 5 and not who.startswith("sp:"):
                    continue
                for t in tables:
                    if rnd.random() < (0.9 if who.startswith("sp:") else 0.55):
                        rows.append((day, pid(who), t, "read", rnd.randint(1, 12 if who.startswith("sp:") else 5), "demo"))
        for who, tables in WRITES.items():
            for d in range(0, 90, 1):
                for t in tables:
                    rows.append((today - dt.timedelta(days=d), pid(who), t, "write", rnd.randint(1, 4), "demo"))
        # admin consultou dado de RH (gatilho de alerta)
        rows.append((today - dt.timedelta(days=3), ids["users"]["carlos.mendes"]["id"],
                     f"{P}.data_people.s__people__employee__snapshot", "read", 2, "demo"))
        cur.execute("DELETE FROM inv_usage WHERE source = 'demo'")
        psycopg2.extras.execute_values(
            cur, "INSERT INTO inv_usage (day, principal_id, securable, action, n, source) VALUES %s "
                 "ON CONFLICT DO NOTHING", rows)
        cur.execute("DELETE FROM inv_creations WHERE source = 'demo'")
        crows = []
        for i, (who, cap, name, loc) in enumerate(CREATIONS):
            crows.append((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=rnd.randint(1, 40), hours=i),
                          pid(who), cap, "7474657351509385", f"demo-{i}", name, loc, "demo"))
        psycopg2.extras.execute_values(
            cur, "INSERT INTO inv_creations (event_time, principal_id, capability, workspace_id, asset_id, "
                 "asset_name, location, source) VALUES %s", crows)
        # admin se auto-atribuiu acesso ao RH
        cur.execute("DELETE FROM inv_permission_events WHERE source = 'demo'")
        cur.execute("""INSERT INTO inv_permission_events (event_time, actor, securable, grantee, detail, source)
                       VALUES (%s, %s, %s, %s, %s, 'demo')""",
                    (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3), email("carlos.mendes"),
                     f"{P}.data_people", email("carlos.mendes"), json.dumps({"add": ["USE_SCHEMA", "SELECT"]})))
        cur.execute("""INSERT INTO workspaces (workspace_id, workspace_name, workspace_url)
                       VALUES ('7474657351509385', 'fevm-fc', 'https://fevm-fc.cloud.databricks.com')
                       ON CONFLICT DO NOTHING""")
    conn.commit()
    conn.close()
    print(f"  Lakebase: modelo + {len(rows)} linhas de uso + {len(CREATIONS)} criações simuladas")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-uc", action="store_true")
    ap.add_argument("--skip-identities", action="store_true")
    args = ap.parse_args()
    w = WorkspaceClient(profile=PROFILE)
    if not args.skip_uc:
        print("1/4 Unity Catalog…")
        setup_uc(w)
    print("2/4 Identidades…")
    if args.skip_identities and MANIFEST.exists():
        ids = json.loads(MANIFEST.read_text())
    else:
        ids = ensure_identities(w)
        MANIFEST.write_text(json.dumps(ids, indent=2))
    print("3/4 GRANTs…")
    apply_grants(w, ids)
    print("4/4 Lakebase…")
    seed_lakebase(w, ids)
    print("ok — rode o job de inventário para popular a visão 360")


if __name__ == "__main__":
    main()
