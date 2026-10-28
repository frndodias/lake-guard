"""SQL via SQL warehouse (Statement Execution API) → lista de dicts."""

from __future__ import annotations

import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import Disposition, Format, StatementState


def warehouse_sql(w: WorkspaceClient, warehouse_id: str):
    def run(stmt: str) -> list[dict]:
        r = w.statement_execution.execute_statement(
            statement=stmt, warehouse_id=warehouse_id, wait_timeout="50s",
            disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
        while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(1)
            r = w.statement_execution.get_statement(r.statement_id)
        if r.status.state != StatementState.SUCCEEDED:
            msg = r.status.error.message if r.status.error else str(r.status.state)
            raise RuntimeError(msg)
        if not r.manifest or not r.manifest.schema or not r.manifest.schema.columns:
            return []
        cols = [c.name for c in r.manifest.schema.columns]
        rows = list(r.result.data_array or []) if r.result else []
        chunk = r.result.next_chunk_index if r.result else None
        while chunk:
            nxt = w.statement_execution.get_statement_result_chunk_n(r.statement_id, chunk)
            rows.extend(nxt.data_array or [])
            chunk = nxt.next_chunk_index
        return [dict(zip(cols, row)) for row in rows]
    return run
