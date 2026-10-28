"""Lakeguard — Motor de detecção (camada detectiva).

Roda como Databricks Job (serverless). A cada execução:
  1. Lê o checkpoint (maior event_time já processado) do Lakebase.
  2. Lê os eventos de criação de assets governados de system.access.audit
     (view fc_catalog.lakeguard.v_creation_events) desde o checkpoint.
  3. Resolve a permissão efetiva de cada principal (grants user + grupos SCIM).
  4. Para quem criou SEM permissão, grava um alerta (idempotente via dedup_key).
     Ignora o que foi criado pelo gateway da app (gateway_events).
  5. Atualiza o checkpoint.

Execução local (dev):  DATABRICKS_PROFILE=fevm-fc python detect_violations.py
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os

import psycopg2
import psycopg2.extras
from databricks.sdk import WorkspaceClient

CATALOG = os.environ.get("LAKEGUARD_CATALOG", "fc_catalog")
SCHEMA = os.environ.get("LAKEGUARD_SCHEMA", "lakeguard")
VIEW = f"{CATALOG}.{SCHEMA}.v_creation_events"
LAKEBASE_INSTANCE = os.environ.get("LAKEGUARD_LAKEBASE_INSTANCE", "lakeguard")
PG_SCHEMA = os.environ.get("LAKEGUARD_PG_SCHEMA", "lakeguard")
LOOKBACK_DAYS_INITIAL = int(os.environ.get("LAKEGUARD_LOOKBACK_DAYS", "1"))
IS_APP = bool(os.environ.get("DATABRICKS_APP_NAME") or os.environ.get("DATABRICKS_RUNTIME_VERSION"))


# --------------------------------------------------------------------------- #
# Clients
# --------------------------------------------------------------------------- #
def get_wc() -> WorkspaceClient:
    if os.environ.get("DATABRICKS_PROFILE") and not IS_APP:
        return WorkspaceClient(profile=os.environ["DATABRICKS_PROFILE"])
    return WorkspaceClient()


def get_spark():
    from pyspark.sql import SparkSession

    return SparkSession.builder.getOrCreate()


def lakebase_conn(wc: WorkspaceClient):
    inst = wc.database.get_database_instance(name=LAKEBASE_INSTANCE)
    cred = wc.database.generate_database_credential(instance_names=[LAKEBASE_INSTANCE])
    user = wc.current_user.me().user_name
    conn = psycopg2.connect(
        host=inst.read_write_dns,
        port=5432,
        dbname=os.environ.get("PGDATABASE", "lakeguard"),
        user=user,
        password=cred.token,
        sslmode="require",
        connect_timeout=15,
    )
    with conn.cursor() as cur:
        cur.execute(f"SET search_path TO {PG_SCHEMA}, public")
    conn.commit()  # persiste o search_path para sobreviver a rollbacks posteriores
    return conn


# --------------------------------------------------------------------------- #
# Permissões
# --------------------------------------------------------------------------- #
def load_grants(conn) -> dict[str, list[tuple[str, str, bool]]]:
    """principal(lower) -> [(capability, workspace_id, allowed)]."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT principal, capability, workspace_id, allowed FROM grants")
        out: dict[str, list[tuple[str, str, bool]]] = {}
        for r in cur.fetchall():
            out.setdefault(r["principal"].lower(), []).append(
                (r["capability"], r["workspace_id"], r["allowed"])
            )
        return out


def load_gateway_asset_ids(conn) -> set[str]:
    """asset_ids criados PELA app (gateway) — allowlist p/ não gerar falso-positivo."""
    with conn.cursor() as cur:
        cur.execute("SELECT asset_id FROM gateway_events WHERE asset_id IS NOT NULL")
        return {r[0] for r in cur.fetchall()}


def build_user_groups(wc: WorkspaceClient) -> dict[str, list[str]]:
    """email(lower) -> [grupos]. Uma passada em todos os grupos do workspace."""
    mapping: dict[str, list[str]] = {}
    for g in wc.groups.list(attributes="displayName,members"):
        for m in (g.members or []):
            if m.display and "@" in m.display:
                mapping.setdefault(m.display.lower(), []).append(g.display_name)
    return mapping


def is_allowed(email: str, capability: str, workspace_id: str, grants: dict, user_groups: dict) -> bool:
    """Escopo do workspace > '*'; dentro do escopo, negação > concessão."""
    principals = [email.lower()] + [gp.lower() for gp in user_groups.get(email.lower(), [])]
    rows = [
        (ws, allowed)
        for p in principals
        for cap, ws, allowed in grants.get(p, [])
        if cap == capability
    ]
    scoped = [a for ws, a in rows if ws == workspace_id] or [a for ws, a in rows if ws == "*"]
    return bool(scoped) and all(scoped)


def sync_workspaces(spark, conn) -> None:
    """Copia nomes/URLs de system.access.workspaces_latest para o Lakebase (filtro da UI).
    Best-effort: se a system table não estiver habilitada, a UI mostra só o id."""
    try:
        rows = spark.sql(
            "SELECT CAST(workspace_id AS STRING) AS workspace_id, workspace_name, workspace_url "
            "FROM system.access.workspaces_latest"
        ).collect()
    except Exception as ex:  # noqa: BLE001
        print(f"[lakeguard] workspaces_latest indisponível: {ex}")
        return
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO workspaces (workspace_id, workspace_name, workspace_url) VALUES %s
            ON CONFLICT (workspace_id) DO UPDATE
            SET workspace_name = EXCLUDED.workspace_name,
                workspace_url  = EXCLUDED.workspace_url,
                updated_at     = now()
            """,
            [(r["workspace_id"], r["workspace_name"], r["workspace_url"]) for r in rows],
        )
    conn.commit()


# --------------------------------------------------------------------------- #
# Detecção
# --------------------------------------------------------------------------- #
def get_checkpoint(conn) -> dt.datetime:
    with conn.cursor() as cur:
        cur.execute("SELECT last_event_time FROM detection_state WHERE id = 1")
        row = cur.fetchone()
    if row and row[0]:
        return row[0]
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=LOOKBACK_DAYS_INITIAL)


def _utc(ts):
    """Spark devolve timestamps tz-naive (sessão UTC no serverless). Torna aware
    para comparar/gravar com segurança contra o checkpoint (TIMESTAMPTZ)."""
    if ts is not None and ts.tzinfo is None:
        return ts.replace(tzinfo=dt.timezone.utc)
    return ts


def dedup_key(request_id, principal, capability, event_time) -> str:
    raw = f"{request_id or ''}|{principal}|{capability}|{event_time}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def fetch_events(spark, since: dt.datetime, enabled_caps: set[str]):
    # Filtra as capacidades habilitadas DENTRO do SQL (evita coletar milhões de
    # eventos de tipos desligados, ex.: clusters automáticos) e faz partition
    # pruning por event_date.
    if not enabled_caps:
        return []
    caps_in = ",".join("'" + c.replace("'", "''") + "'" for c in enabled_caps)
    df = spark.sql(
        f"""
        SELECT event_time, principal, capability, service_name, action_name,
               workspace_id, source_ip, request_id, request_params, response_result
        FROM {VIEW}
        WHERE event_date > DATE '{since.strftime('%Y-%m-%d')}' - INTERVAL 1 DAY
          AND event_time > TIMESTAMP '{since.strftime('%Y-%m-%d %H:%M:%S')}'
          AND capability IN ({caps_in})
          AND principal IS NOT NULL
        ORDER BY event_time
        """
    )
    return df.collect()


def extract_asset(capability: str, request_params, response) -> tuple[str | None, str | None]:
    """Best-effort: extrai (asset_id, asset_name) de request_params/response."""
    rp = request_params or {}
    resp = {}
    try:
        resp = json.loads(response) if isinstance(response, str) else (response or {})
    except Exception:  # noqa: BLE001
        resp = {}
    name = rp.get("name") or rp.get("dashboard_name") or rp.get("display_name")
    aid = (
        resp.get("job_id") or resp.get("id") or resp.get("dashboard_id")
        or resp.get("space_id") or resp.get("endpoint_id") or resp.get("pipeline_id")
    )
    return (str(aid) if aid is not None else None), name


def main():
    wc = get_wc()
    spark = get_spark()
    conn = lakebase_conn(wc)
    started = dt.datetime.now(dt.timezone.utc)
    try:
        sync_workspaces(spark, conn)
        grants = load_grants(conn)
        gateway_ids = load_gateway_asset_ids(conn)
        user_groups = build_user_groups(wc)
        since = get_checkpoint(conn)

        # severidade/enabled ANTES do fetch — filtramos as capacidades no SQL
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT code, default_severity FROM capabilities WHERE enabled")
            severity = {r["code"]: r["default_severity"] for r in cur.fetchall()}
            enabled = set(severity.keys())

        events = fetch_events(spark, since, enabled)
        max_event = since
        inserted = 0
        with conn.cursor() as cur:
            for e in events:
                cap = e["capability"]
                principal = e["principal"]
                et = _utc(e["event_time"])
                if et and et > max_event:
                    max_event = et
                if cap not in enabled:
                    continue
                if is_allowed(principal, cap, str(e["workspace_id"]), grants, user_groups):
                    continue  # autorizado — sem alerta
                asset_id, asset_name = extract_asset(cap, e["request_params"], e["response_result"])
                if asset_id and asset_id in gateway_ids:
                    continue  # criado pelo gateway da app (autorizado) — sem alerta
                key = dedup_key(e["request_id"], principal, cap, et)
                cur.execute(
                    """
                    INSERT INTO alerts (principal, capability, asset_type, asset_id, asset_name,
                                        service_name, action_name, workspace_id, source_ip,
                                        event_time, severity, dedup_key, raw_event)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (dedup_key) DO NOTHING
                    """,
                    (
                        principal, cap, cap, asset_id, asset_name,
                        e["service_name"], e["action_name"], str(e["workspace_id"]),
                        e["source_ip"], et, severity.get(cap, "warning"),
                        key, json.dumps({"request_params": e["request_params"]}, default=str),
                    ),
                )
                inserted += cur.rowcount

            cur.execute(
                """
                UPDATE detection_state
                SET last_event_time = %s, last_run_at = %s, last_run_status = 'ok', last_error = NULL
                WHERE id = 1
                """,
                (max_event, started),
            )
        conn.commit()
        print(f"[lakeguard] eventos={len(events)} alertas_novos={inserted} checkpoint={max_event}")
    except Exception as ex:  # noqa: BLE001
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE detection_state SET last_run_at=%s, last_run_status='error', last_error=%s WHERE id=1",
                (started, str(ex)),
            )
        conn.commit()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
