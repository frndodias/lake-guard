"""Configuração e autenticação do Lakeguard.

Centraliza:
  - identidade/host do workspace (WorkspaceClient)
  - descoberta do SQL warehouse
  - conexão Lakebase (Postgres) — app (env auto-injetadas) ou dev local (CLI)

Regra de ouro: NUNCA hardcodar tokens. Em produção (Databricks App) as
credenciais vêm do ambiente; localmente, do profile do CLI.
"""

from __future__ import annotations

import os
from functools import lru_cache

from databricks.sdk import WorkspaceClient

# --------------------------------------------------------------------------- #
# Contexto de execução
# --------------------------------------------------------------------------- #
IS_DATABRICKS_APP = bool(os.environ.get("DATABRICKS_APP_NAME"))
IN_JOB = bool(os.environ.get("DATABRICKS_RUNTIME_VERSION"))
LOCAL_PROFILE = os.environ.get("DATABRICKS_PROFILE", "fevm-fc")
# usuário assumido no dev local (sem os headers do Databricks Apps)
LOCAL_DEV_EMAIL = os.environ.get("LAKEGUARD_LOCAL_EMAIL", "fernando.custodio@databricks.com")

# Unity Catalog (camada analítica)
CATALOG = os.environ.get("LAKEGUARD_CATALOG", "fc_catalog")
SCHEMA = os.environ.get("LAKEGUARD_SCHEMA", "lakeguard")
VIEW_CREATION_EVENTS = f"{CATALOG}.{SCHEMA}.v_creation_events"

# Lakebase (camada operacional)
LAKEBASE_INSTANCE = os.environ.get("LAKEGUARD_LAKEBASE_INSTANCE", "lakeguard")
LAKEBASE_DB = os.environ.get("PGDATABASE", "lakeguard")
PG_SCHEMA = os.environ.get("LAKEGUARD_PG_SCHEMA", "lg")

# Job de inventário (disparo pela UI)
INVENTORY_JOB_ID = os.environ.get("INVENTORY_JOB_ID", "")

# Conta (rule sets de group manager)
ACCOUNT_ID = os.environ.get("LAKEGUARD_ACCOUNT_ID", "")

# Admins garantidos (bootstrap do controle de acesso do app)
BOOTSTRAP_ADMINS = [e.strip().lower() for e in os.environ.get("LAKEGUARD_BOOTSTRAP_ADMINS", "").split(",") if e.strip()]


@lru_cache(maxsize=1)
def get_workspace_client() -> WorkspaceClient:
    """WorkspaceClient com auth da app (SP) em produção ou profile no dev."""
    if IS_DATABRICKS_APP or IN_JOB:
        return WorkspaceClient()
    return WorkspaceClient(profile=LOCAL_PROFILE)


@lru_cache(maxsize=1)
def get_app_workspace_id() -> str:
    wid = os.environ.get("DATABRICKS_WORKSPACE_ID")
    if wid:
        return str(wid)
    return str(get_workspace_client().get_workspace_id())


@lru_cache(maxsize=1)
def app_principal() -> str:
    """Nome do principal que o app usa para aplicar (applicationId do SP ou e-mail no dev)."""
    if IS_DATABRICKS_APP:
        return os.environ.get("DATABRICKS_CLIENT_ID", "")
    return get_workspace_client().current_user.me().user_name


@lru_cache(maxsize=1)
def get_warehouse_id() -> str:
    """ID do SQL warehouse: env WAREHOUSE_ID ou descobre um em execução."""
    wid = os.environ.get("WAREHOUSE_ID")
    if wid:
        return wid
    w = get_workspace_client()
    whs = [wh for wh in w.warehouses.list() if (wh.warehouse_type and wh.warehouse_type.value != "REALTIME")]
    running = [wh for wh in whs if wh.state and wh.state.value == "RUNNING"]
    if running:
        return running[0].id
    if whs:
        return whs[0].id
    raise RuntimeError("Nenhum SQL warehouse encontrado. Defina WAREHOUSE_ID.")


def sql():
    from server.sqlexec import warehouse_sql
    return warehouse_sql(get_workspace_client(), get_warehouse_id())


# --------------------------------------------------------------------------- #
# Lakebase (Postgres)
# --------------------------------------------------------------------------- #
def _lakebase_params_app() -> dict:
    """Produção: o resource Database Instance injeta PGHOST/PGUSER/PGDATABASE,
    mas NÃO a senha — ela é um token OAuth de curta duração que geramos via SDK
    usando o service principal da app."""
    w = get_workspace_client()
    host = os.environ.get("PGHOST") or w.database.get_database_instance(
        name=LAKEBASE_INSTANCE
    ).read_write_dns
    user = os.environ.get("PGUSER") or os.environ.get("DATABRICKS_CLIENT_ID")
    token = w.database.generate_database_credential(
        instance_names=[LAKEBASE_INSTANCE]
    ).token
    return {
        "host": host,
        "port": int(os.environ.get("PGPORT", "5432")),
        "dbname": os.environ.get("PGDATABASE", LAKEBASE_DB),
        "user": user,
        "password": token,
        "sslmode": os.environ.get("PGSSLMODE", "require"),
    }


@lru_cache(maxsize=1)
def _local_host_user() -> tuple[str, str]:
    w = get_workspace_client()
    host = w.database.get_database_instance(name=LAKEBASE_INSTANCE).read_write_dns
    return host, w.current_user.me().user_name


def _lakebase_params_local() -> dict:
    """Dev local e job: host da instância + credencial OAuth do usuário corrente."""
    host, user = _local_host_user()
    token = get_workspace_client().database.generate_database_credential(
        instance_names=[LAKEBASE_INSTANCE]).token
    return {"host": host, "port": 5432, "dbname": LAKEBASE_DB, "user": user,
            "password": token, "sslmode": "require"}


def lakebase_params() -> dict:
    return _lakebase_params_app() if IS_DATABRICKS_APP else _lakebase_params_local()
