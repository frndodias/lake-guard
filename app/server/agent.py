"""Agente de construção de assets — powered by ai-dev-kit (databricks-tools-core).

Loop de tool-calling: o LLM do Unity (Claude Sonnet 5) usa as funções do
ai-dev-kit para explorar dados (Unity Catalog, SQL) e criar assets. Toda tool
de CRIAÇÃO passa antes pelo gate de permissão do Lakeguard.
"""

from __future__ import annotations

import json
from typing import Any

from server import db
from server.config import LLM_ENDPOINT, get_app_workspace_id, get_warehouse_id, get_workspace_client
from server.services import effective_permissions, user_groups


def _serialize(obj: Any) -> str:
    def default(o):
        if hasattr(o, "model_dump"):
            return o.model_dump()
        if hasattr(o, "__dict__"):
            return o.__dict__
        return str(o)
    try:
        return json.dumps(obj, default=default)[:6000]
    except Exception:  # noqa: BLE001
        return str(obj)[:6000]


TOOLS = [
    {"type": "function", "function": {
        "name": "list_catalogs", "description": "Lista os catálogos do Unity Catalog.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "list_schemas", "description": "Lista os schemas de um catálogo.",
        "parameters": {"type": "object", "properties": {"catalog": {"type": "string"}}, "required": ["catalog"]},
    }},
    {"type": "function", "function": {
        "name": "list_tables", "description": "Lista as tabelas de um schema.",
        "parameters": {"type": "object", "properties": {"catalog": {"type": "string"}, "schema": {"type": "string"}}, "required": ["catalog", "schema"]},
    }},
    {"type": "function", "function": {
        "name": "run_sql", "description": "Executa um SELECT (somente leitura/exploração) e retorna as linhas.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "create_job", "description": "Cria um Databricks Job que roda um notebook. Requer permissão 'job'.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"},
            "notebook_path": {"type": "string", "description": "caminho do notebook, ex: /Workspace/Users/.../nb"},
        }, "required": ["name", "notebook_path"]},
    }},
]

SYSTEM = (
    "Você é o agente do Lakeguard que constrói assets no Databricks usando as ferramentas do ai-dev-kit. "
    "Explore os dados com as tools de leitura (list_catalogs, list_schemas, list_tables, run_sql) e crie assets "
    "com as tools de criação. run_sql é SOMENTE leitura (SELECT/SHOW/DESCRIBE). "
    "Seja objetivo; ao terminar, responda em português resumindo o que fez (inclua ids criados). "
    "Se uma criação for negada por permissão, explique ao usuário qual permissão falta."
)


def run_agent(prompt: str, user_email: str, max_iters: int = 8) -> dict:
    from databricks_tools_core.sql import execute_sql
    from databricks_tools_core.unity_catalog import list_catalogs, list_schemas, list_tables
    from databricks_tools_core.jobs import create_job

    wid = get_warehouse_id()
    groups = user_groups(user_email)
    perms = effective_permissions(user_email, groups, get_app_workspace_id())

    def dispatch(name: str, args: dict) -> Any:
        if name == "list_catalogs":
            return list_catalogs()
        if name == "list_schemas":
            return list_schemas(args["catalog"])
        if name == "list_tables":
            return list_tables(args["catalog"], args["schema"])
        if name == "run_sql":
            q = args["query"].strip()
            if not q.lower().startswith(("select", "show", "describe", "desc", "with", "explain")):
                return {"error": "run_sql é somente leitura (use SELECT/SHOW/DESCRIBE)."}
            return execute_sql(q, warehouse_id=wid, timeout=120)
        if name == "create_job":
            if not perms.get("job", {}).get("allowed"):
                return {"denied": True, "message": f"{user_email} não tem permissão para criar 'job'."}
            tasks = [{"task_key": "main", "notebook_task": {"notebook_path": args["notebook_path"], "source": "WORKSPACE"}}]
            res = create_job(name=args["name"], tasks=tasks)
            job_id = res.get("job_id") if isinstance(res, dict) else getattr(res, "job_id", None)
            db.execute(
                "INSERT INTO gateway_events (principal, capability, asset_type, asset_id, asset_name, detail) VALUES (%s,%s,%s,%s,%s,%s)",
                (user_email, "job", "job", str(job_id), args["name"], json.dumps(args)),
            )
            return {"created": True, "job_id": job_id, "name": args["name"]}
        return {"error": f"tool desconhecida: {name}"}

    client = get_workspace_client().serving_endpoints.get_open_ai_client()
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": prompt},
    ]
    transcript: list[dict] = []

    for _ in range(max_iters):
        resp = client.chat.completions.create(model=LLM_ENDPOINT, messages=messages, tools=TOOLS)
        m = resp.choices[0].message
        if not m.tool_calls:
            return {"answer": m.content, "transcript": transcript}

        messages.append({
            "role": "assistant",
            "content": m.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in m.tool_calls
            ],
        })
        for tc in m.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:  # noqa: BLE001
                args = {}
            try:
                result = dispatch(name, args)
            except Exception as e:  # noqa: BLE001
                result = {"error": f"{type(e).__name__}: {e}"}
            transcript.append({"tool": name, "args": args, "result": _serialize(result)[:600]})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": _serialize(result)})

    return {"answer": "(limite de iterações atingido)", "transcript": transcript}
