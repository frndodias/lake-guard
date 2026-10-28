"""Agente MCP-backed — consome as tools do app ai-dev-kit (databricks-mcp-server).

Os schemas das tools vêm DIRETO do MCP (zero drift). O LLM do Unity decide quais
chamar; cada tool é curada (allowlist) e as ações de ESCRITA passam pelo gate de
permissão do Lakeguard antes de executar no app MCP (via OBO do SP do Lakeguard).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from server import db
from server.config import LLM_ENDPOINT, MCP_APP_URL, get_app_workspace_id, get_workspace_client
from server.mcp_client import _sp_bearer
from server.services import effective_permissions, user_groups

# Tools do MCP expostas ao agente (curadas — nada destrutivo/perigoso solto).
EXPOSED = {
    # leitura / exploração
    "execute_sql", "get_table_stats_and_schema", "manage_warehouse",
    "list_compute", "get_current_user", "ask_genie",
    # criação (gated por capability quando action for de escrita)
    "manage_jobs", "manage_dashboard", "manage_pipeline",
    "manage_vs_endpoint", "manage_vs_index", "manage_genie",
    "manage_app", "manage_cluster", "manage_sql_warehouse",
    "manage_lakebase_database", "manage_uc_objects",
}

# tool "grossa" -> capability do Lakeguard (gate aplicado quando action é escrita)
TOOL_CAP = {
    "manage_jobs": "job",
    "manage_dashboard": "dashboard",
    "manage_pipeline": "pipeline",
    "manage_vs_endpoint": "vector_search",
    "manage_vs_index": "vector_index",
    "manage_genie": "genie",
    "manage_app": "app",
    "manage_cluster": "cluster",
    "manage_sql_warehouse": "warehouse",
    "manage_lakebase_database": "lakebase",
}
WRITE_ACTIONS = {"create", "update", "delete", "deploy", "trash", "edit", "add", "remove", "set"}

SYSTEM = (
    "Você é o agente do Lakeguard que constrói assets no Databricks usando as ferramentas do ai-dev-kit "
    "(expostas via MCP). Fale sempre em português.\n\n"
    "FLUXO OBRIGATÓRIO antes de CRIAR qualquer asset (tools manage_* com action create/update/delete):\n"
    "1. ENTENDA o contexto usando as tools de LEITURA (explorar catálogos/schemas/tabelas, schema/stats, "
    "execute_sql somente leitura) para descobrir os dados relevantes.\n"
    "2. PERGUNTE o que faltar — NÃO assuma. Ex.: qual catálogo/tabela usar, quais KPIs/visões, nome do "
    "asset, se deve ser publicado/privado, schedule, etc.\n"
    "3. Apresente um PLANO objetivo do que vai criar e PEÇA CONFIRMAÇÃO explícita, terminando com algo como "
    "'Posso criar? Confirme para eu prosseguir.'\n"
    "4. Só chame a tool de criação DEPOIS que o usuário confirmar.\n\n"
    "As tools de leitura podem ser usadas livremente, sem pedir confirmação, mas seja EFICIENTE: "
    "explore o suficiente para entender (não rode dezenas de queries). "
    "NUNCA crie um asset na primeira mensagem da conversa — primeiro entenda e planeje. "
    "Se uma criação for negada por permissão, explique qual permissão falta. "
    "Após criar, responda com um resumo curto (nome, id, link se houver)."
)


def _mcp_session():
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    return Client(StreamableHttpTransport(url=MCP_APP_URL, headers={"Authorization": f"Bearer {_sp_bearer()}"}))


def _result_text(res: Any) -> str:
    data = getattr(res, "data", None)
    if data is not None:
        try:
            return json.dumps(data, default=str)[:6000]
        except Exception:  # noqa: BLE001
            return str(data)[:6000]
    content = getattr(res, "content", None)
    if content:
        texts = [getattr(b, "text", "") for b in content if getattr(b, "text", "")]
        return ("\n".join(texts))[:6000]
    return str(res)[:6000]


async def run_agent_mcp(
    prompt: str, user_email: str, history: list[dict] | None = None, max_iters: int = 14
) -> dict:
    groups = user_groups(user_email)
    perms = effective_permissions(user_email, groups, get_app_workspace_id())
    oai = get_workspace_client().serving_endpoints.get_open_ai_client()
    first_turn = not (history or [])  # True = primeira mensagem da conversa

    def gate(tool_name: str, args: dict) -> str | None:
        """Retorna mensagem de bloqueio, ou None se liberado."""
        cap = TOOL_CAP.get(tool_name)
        if not cap:
            if tool_name == "execute_sql":
                q = str(args.get("sql_query") or args.get("query") or "").strip().lower()
                if q and not q.startswith(("select", "show", "describe", "desc", "with", "explain")):
                    return "execute_sql é somente leitura neste agente (use SELECT/SHOW/DESCRIBE)."
            return None
        action = str(args.get("action") or "").lower()
        if action in WRITE_ACTIONS:
            if not perms.get(cap, {}).get("allowed"):
                return f"PERMISSÃO NEGADA: {user_email} não tem permissão para criar/alterar '{cap}'. Explique isso ao usuário."
            if first_turn:
                return (
                    "AINDA NÃO CRIE. Esta é a primeira mensagem da conversa. Primeiro explore os dados "
                    "(tools de leitura), pergunte o que faltar (catálogo/tabela, KPIs, nome, publicar ou não) "
                    "e apresente um PLANO pedindo confirmação. Só crie depois que o usuário confirmar."
                )
        return None

    transcript: list[dict] = []

    async with _mcp_session() as mcp:
        mcp_tools = await mcp.list_tools()
        tools_spec = [
            {"type": "function", "function": {
                "name": t.name,
                "description": (t.description or "")[:1000],
                "parameters": (getattr(t, "inputSchema", None) or {"type": "object", "properties": {}}),
            }}
            for t in mcp_tools if t.name in EXPOSED
        ]

        messages: list[dict] = [{"role": "system", "content": SYSTEM}]
        for h in (history or []):
            if h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": prompt})

        for _ in range(max_iters):
            resp = await asyncio.to_thread(
                oai.chat.completions.create, model=LLM_ENDPOINT, messages=messages, tools=tools_spec
            )
            m = resp.choices[0].message
            if not m.tool_calls:
                return {"answer": m.content, "transcript": transcript}

            messages.append({
                "role": "assistant", "content": m.content or "",
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

                denial = gate(name, args)
                if denial:
                    out = {"blocked": True, "message": denial}
                else:
                    try:
                        res = await mcp.call_tool(name, args)
                        out_text = _result_text(res)
                        out = {"ok": True, "result": out_text}
                        # loga criação autorizada (allowlist da detecção)
                        cap = TOOL_CAP.get(name)
                        if cap and str(args.get("action", "")).lower() == "create":
                            db.execute(
                                "INSERT INTO gateway_events (principal, capability, asset_type, asset_name, detail) VALUES (%s,%s,%s,%s,%s)",
                                (user_email, cap, cap, args.get("name"), json.dumps(args)[:2000]),
                            )
                    except Exception as e:  # noqa: BLE001
                        out = {"error": f"{type(e).__name__}: {e}"}

                transcript.append({"tool": name, "args": args, "result": json.dumps(out, default=str)[:600]})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(out, default=str)[:6000]})

    return {"answer": "(limite de iterações atingido)", "transcript": transcript}
