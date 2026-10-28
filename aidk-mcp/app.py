"""Lakeguard — ai-dev-kit MCP server hospedado como Databricks App (HTTP).

Importa o FastMCP já montado pelo databricks-mcp-server (as tools se registram
por side-effect no import) e o serve via streamable-HTTP na porta do app.
Autentica no Databricks pelo service principal do próprio app (OAuth M2M,
detectado automaticamente pela auth do ai-dev-kit).
"""

from __future__ import annotations

import os

from databricks_mcp_server.server import mcp  # noqa: E402  (registra todas as tools)

if __name__ == "__main__":
    port = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
    # FastMCP 3.x: transport "http" = streamable-HTTP (endpoint em /mcp/)
    mcp.run(transport="http", host="0.0.0.0", port=port)
