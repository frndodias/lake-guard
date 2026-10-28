"""Cliente MCP do Lakeguard para o app ai-dev-kit (databricks-mcp-server).

Autentica app-a-app: minta o token OAuth do service principal do Lakeguard e o
apresenta como Bearer ao app MCP (que exige CAN_USE para o SP). Conexão via
streamable-HTTP (FastMCP).
"""

from __future__ import annotations

from typing import Any

from databricks.sdk.core import Config

from server.config import MCP_APP_URL


def _sp_bearer() -> str:
    """Token OAuth do SP do app (OAuth M2M a partir do ambiente)."""
    cfg = Config()
    headers = cfg.authenticate()  # {'Authorization': 'Bearer ...'}
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise RuntimeError("não foi possível obter token OAuth do SP")
    return auth.split(" ", 1)[1]


def _client():
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    transport = StreamableHttpTransport(
        url=MCP_APP_URL,
        headers={"Authorization": f"Bearer {_sp_bearer()}"},
    )
    return Client(transport)


async def list_tools() -> list[dict[str, Any]]:
    async with _client() as c:
        tools = await c.list_tools()
    return [
        {
            "name": t.name,
            "description": (t.description or "")[:300],
            "input_schema": getattr(t, "inputSchema", None) or getattr(t, "input_schema", None),
        }
        for t in tools
    ]


async def call_tool(name: str, arguments: dict) -> Any:
    async with _client() as c:
        res = await c.call_tool(name, arguments)
    # FastMCP CallToolResult: .data (estruturado) ou .content (blocos de texto)
    data = getattr(res, "data", None)
    if data is not None:
        return data
    content = getattr(res, "content", None)
    if content:
        texts = [getattr(b, "text", None) for b in content if getattr(b, "text", None)]
        return "\n".join(texts) if texts else str(content)
    return str(res)
