"""Agente Genie — text-to-SQL sobre permissões e eventos de criação."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.config import GENIE_SPACE_ID, get_workspace_client

router = APIRouter(prefix="/api")


class AskIn(BaseModel):
    question: str = Field(..., min_length=1)
    conversation_id: str | None = None


@router.get("/genie/status")
async def genie_status():
    return {"configured": bool(GENIE_SPACE_ID), "space_id": GENIE_SPACE_ID or None}


@router.post("/genie/ask")
async def genie_ask(body: AskIn):
    if not GENIE_SPACE_ID:
        raise HTTPException(status_code=503, detail="GENIE_SPACE_ID não configurado")
    w = get_workspace_client()
    try:
        if body.conversation_id:
            msg = w.genie.create_message_and_wait(
                space_id=GENIE_SPACE_ID,
                conversation_id=body.conversation_id,
                content=body.question,
            )
        else:
            msg = w.genie.start_conversation_and_wait(
                space_id=GENIE_SPACE_ID, content=body.question
            )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Falha no Genie: {e}") from e

    text_parts, query_text, rows = [], None, None
    for att in (msg.attachments or []):
        if att.text and att.text.content:
            text_parts.append(att.text.content)
        if att.query:
            query_text = att.query.query
            try:
                result = w.genie.get_message_query_result(
                    space_id=GENIE_SPACE_ID,
                    conversation_id=msg.conversation_id,
                    message_id=msg.id,
                )
                sr = result.statement_response
                if sr and sr.result and sr.result.data_array:
                    cols = [c.name for c in sr.manifest.schema.columns]
                    rows = [dict(zip(cols, r)) for r in sr.result.data_array]
            except Exception:  # noqa: BLE001
                pass

    return {
        "conversation_id": msg.conversation_id,
        "message_id": msg.id,
        "answer": "\n\n".join(text_parts) or None,
        "sql": query_text,
        "rows": rows,
    }
