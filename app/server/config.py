"""Configuração e autenticação do Lakeguard.

Centraliza:
  - identidade/host do workspace (WorkspaceClient)
  - descoberta do SQL warehouse
  - conexão Lakebase (Postgres) — app (env auto-injetadas) ou dev local (CLI)
  - autenticação on-behalf-of (OBO) para o gateway de criação

Regra de ouro: NUNCA hardcodar tokens. Em produção (Databricks App) as
credenciais vêm do ambiente; localmente, do profile do CLI.
"""

from __future__ import annotations

import json
import os
import subprocess
from functools import lru_cache

from databricks.sdk import WorkspaceClient

# --------------------------------------------------------------------------- #
# Contexto de execução
# --------------------------------------------------------------------------- #
IS_DATABRICKS_APP = bool(os.environ.get("DATABRICKS_APP_NAME"))
LOCAL_PROFILE = os.environ.get("DATABRICKS_PROFILE", "fevm-fc")

# Unity Catalog (camada analítica)
CATALOG = os.environ.get("LAKEGUARD_CATALOG", "fc_catalog")
SCHEMA = os.environ.get("LAKEGUARD_SCHEMA", "lakeguard")
VIEW_CREATION_EVENTS = f"{CATALOG}.{SCHEMA}.v_creation_events"

# Lakebase (camada operacional)
LAKEBASE_INSTANCE = os.environ.get("LAKEGUARD_LAKEBASE_INSTANCE", "lakeguard")
LAKEBASE_DB = os.environ.get("PGDATABASE", "lakeguard")
PG_SCHEMA = os.environ.get("LAKEGUARD_PG_SCHEMA", "lakeguard")

# Genie (agente text-to-SQL sobre as permissões/eventos)
GENIE_SPACE_ID = os.environ.get("GENIE_SPACE_ID", "")

# Foundation Model p/ criação por linguagem natural (ai-dev-kit)
LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "databricks-claude-sonnet-5")

# App MCP do ai-dev-kit (consumido como cliente MCP)
MCP_APP_URL = os.environ.get(
    "MCP_APP_URL",
    "https://lakeguard-aidk-mcp-7474657351509385.aws.databricksapps.com/mcp",
)

# Job de detecção (para disparo manual pela UI, opcional)
DETECTION_JOB_ID = os.environ.get("DETECTION_JOB_ID", "")


@lru_cache(maxsize=1)
def get_workspace_client() -> WorkspaceClient:
    """WorkspaceClient com auth da app (SP) em produção ou profile no dev."""
    if IS_DATABRICKS_APP:
        return WorkspaceClient()
    return WorkspaceClient(profile=LOCAL_PROFILE)


def get_user_client(user_token: str) -> WorkspaceClient:
    """WorkspaceClient agindo COMO o usuário logado (on-behalf-of).

    Usado pelo gateway de criação: o asset nasce com o dono correto e o
    audit log atribui a ação ao usuário, não ao service principal da app.
    auth_type='pat' evita conflito com o OAuth do SP injetado no ambiente.
    """
    return WorkspaceClient(
        host=get_workspace_client().config.host,
        token=user_token,
        auth_type="pat",
    )


@lru_cache(maxsize=1)
def get_app_workspace_id() -> str:
    """Workspace onde a app roda (onde o gateway/agente cria e remedia assets)."""
    wid = os.environ.get("DATABRICKS_WORKSPACE_ID")
    if wid:
        return str(wid)
    return str(get_workspace_client().get_workspace_id())


@lru_cache(maxsize=1)
def get_warehouse_id() -> str:
    """ID do SQL warehouse: env WAREHOUSE_ID ou descobre um em execução."""
    wid = os.environ.get("WAREHOUSE_ID")
    if wid:
        return wid
    w = get_workspace_client()
    running = [wh for wh in w.warehouses.list() if wh.state and wh.state.value == "RUNNING"]
    if running:
        return running[0].id
    for wh in w.warehouses.list():
        return wh.id
    raise RuntimeError("Nenhum SQL warehouse encontrado. Defina WAREHOUSE_ID.")


def warehouse_http_path() -> str:
    return f"/sql/1.0/warehouses/{get_warehouse_id()}"


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


def _lakebase_params_local() -> dict:
    """Dev local: descobre host da instância e gera credencial OAuth via CLI."""
    inst = subprocess.run(
        ["databricks", "database", "get-database-instance", LAKEBASE_INSTANCE,
         "-p", LOCAL_PROFILE, "-o", "json"],
        capture_output=True, text=True, check=True,
    )
    host = json.loads(inst.stdout)["read_write_dns"]

    cred = subprocess.run(
        ["databricks", "database", "generate-database-credential",
         "--json", json.dumps({"instance_names": [LAKEBASE_INSTANCE]}),
         "-p", LOCAL_PROFILE, "-o", "json"],
        capture_output=True, text=True, check=True,
    )
    token = json.loads(cred.stdout)["token"]

    me = subprocess.run(
        ["databricks", "current-user", "me", "-p", LOCAL_PROFILE, "-o", "json"],
        capture_output=True, text=True, check=True,
    )
    user = json.loads(me.stdout)["userName"]

    return {
        "host": host,
        "port": 5432,
        "dbname": LAKEBASE_DB,
        "user": user,
        "password": token,
        "sslmode": "require",
    }


def lakebase_params() -> dict:
    return _lakebase_params_app() if IS_DATABRICKS_APP else _lakebase_params_local()
