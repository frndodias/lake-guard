"""Lakeguard — job de inventário 360 e regras.

A cada execução:
  1. coleta identidades, objetos, GRANTs, tags, uso e criações (server.inventory)
  2. regrava o espelho no Lakebase (schema lg) e a cópia analítica em Delta
  3. avalia as regras e atualiza os alertas
  4. expira acessos temporários vencidos (remove membros com prazo)

No job (serverless) usa Spark para as system tables; localmente usa o SQL
warehouse:  DATABRICKS_PROFILE=fevm-fc python jobs/inventory/run.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _add_app_to_path() -> None:
    here = Path(__file__).resolve() if "__file__" in globals() else Path.cwd()
    for base in [here.parent, *here.parents]:
        if (base / "app" / "server").is_dir():
            sys.path.insert(0, str(base / "app"))
            return
    raise RuntimeError("pasta app/server não encontrada")


_add_app_to_path()
os.environ.setdefault("LAKEGUARD_PG_SCHEMA", "lg")

import psycopg2  # noqa: E402
from databricks.sdk import WorkspaceClient  # noqa: E402

from server import inventory  # noqa: E402

IN_JOB = bool(os.environ.get("DATABRICKS_RUNTIME_VERSION"))
CATALOG = os.environ.get("LAKEGUARD_CATALOG", "fc_catalog")
SCHEMA = os.environ.get("LAKEGUARD_SCHEMA", "lakeguard")
LAKEBASE_INSTANCE = os.environ.get("LAKEGUARD_LAKEBASE_INSTANCE", "lakeguard")


def get_wc() -> WorkspaceClient:
    if not IN_JOB and os.environ.get("DATABRICKS_PROFILE"):
        return WorkspaceClient(profile=os.environ["DATABRICKS_PROFILE"])
    return WorkspaceClient()


def lakebase_conn(w: WorkspaceClient):
    inst = w.database.get_database_instance(name=LAKEBASE_INSTANCE)
    cred = w.database.generate_database_credential(instance_names=[LAKEBASE_INSTANCE])
    conn = psycopg2.connect(host=inst.read_write_dns, port=5432, dbname=os.environ.get("PGDATABASE", "lakeguard"),
                            user=w.current_user.me().user_name, password=cred.token, sslmode="require",
                            connect_timeout=15)
    with conn.cursor() as cur:
        cur.execute("SET search_path TO lg, public")
    conn.commit()
    return conn


def sql_fn(w: WorkspaceClient):
    if IN_JOB:
        from pyspark.sql import SparkSession
        spark = SparkSession.builder.getOrCreate()
        return lambda q: [r.asDict() for r in spark.sql(q).collect()], spark
    from server.sqlexec import warehouse_sql
    return warehouse_sql(w, os.environ.get("WAREHOUSE_ID", "02a3a16cad439d0b")), None


def write_delta(spark, inv: dict) -> None:
    """Cópia analítica (Genie/dashboards) em fc_catalog.lakeguard.inv_*."""
    import pandas as pd

    def save(name: str, rows: list[dict]):
        if not rows:
            return
        df = spark.createDataFrame(pd.DataFrame(rows).astype(str))
        df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.{SCHEMA}.{name}")

    save("inv_principals", inv["principals"])
    save("inv_memberships", [{"group_id": g, "member_id": m} for g, ms in inv["members"].items() for m in ms])
    save("inv_closure", [{"member_id": m, "group_id": g, "depth": d, "path": " > ".join(p)}
                         for m, gs in inv["closure"].items() for g, (d, p) in gs.items()])
    save("inv_securables", inv["securables"])
    save("inv_grants", inv["grants"])
    save("inv_usage", inv["usage"])


def main() -> None:
    w = get_wc()
    conn = lakebase_conn(w)
    sql, spark = sql_fn(w)
    try:
        inv = inventory.run_inventory(w, sql, conn)
        print(f"[lakeguard] inventário: {len(inv['principals'])} identidades, {len(inv['securables'])} objetos, "
              f"{len(inv['grants'])} GRANTs, {len(inv['usage'])} linhas de uso real")
        if spark is not None:
            write_delta(spark, inv)
        try:
            from server import rules, workflow
            n = rules.evaluate()
            print(f"[lakeguard] regras: {n} alertas abertos")
            exp = workflow.expire_due(w, actor="job")
            print(f"[lakeguard] expirados: {exp}")
        except ImportError:
            pass
    except Exception as ex:  # noqa: BLE001
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("UPDATE inv_state SET last_run_at = now(), status = 'error', error = %s WHERE id = 1",
                        (str(ex)[:2000],))
        conn.commit()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
