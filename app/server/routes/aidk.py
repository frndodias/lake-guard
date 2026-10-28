"""Diagnóstico da integração com o ai-dev-kit (databricks-tools-core)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from server.auth import current_user

router = APIRouter(prefix="/api")


class AgentRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


@router.get("/mcp/tools")
async def mcp_tools():
    """Diagnóstico: autentica no app MCP (app-a-app) e lista as tools do ai-dev-kit."""
    from server import mcp_client
    try:
        tools = await mcp_client.list_tools()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}") from e
    return {"count": len(tools), "tools": [{"name": t["name"], "description": t["description"]} for t in tools]}


@router.post("/agent")
async def agent(body: AgentRequest, request: Request):
    """Agente ai-dev-kit via MCP: explora dados e cria assets (governado)."""
    u = current_user(request)
    if not u.email:
        raise HTTPException(status_code=401, detail="não autenticado")
    from server.agent_mcp import run_agent_mcp
    try:
        return await run_agent_mcp(body.prompt, u.email)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}") from e


@router.get("/aidk/health")
async def aidk_health():
    """Confirma que o databricks-tools-core está instalado e autentica (SP)."""
    try:
        import databricks_tools_core as dtc  # noqa: F401
        from databricks_tools_core.auth import get_current_username, get_workspace_client
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"import falhou: {type(e).__name__}: {e}") from e

    try:
        user = get_current_username()
        host = get_workspace_client().config.host
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"auth falhou: {type(e).__name__}: {e}") from e

    return {
        "installed": True,
        "version": getattr(dtc, "__version__", "?"),
        "authenticated_as": user,
        "host": host,
    }
