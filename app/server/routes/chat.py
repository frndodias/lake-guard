"""Chat do agente de criação — conversas e histórico por usuário."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from server import db
from server.auth import current_user

router = APIRouter(prefix="/api")


class ChatIn(BaseModel):
    prompt: str = Field(..., min_length=1)
    conversation_id: int | None = None


class RenameIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


def _own_conversation(conv_id: int, email: str) -> dict:
    conv = db.query_one(
        "SELECT * FROM conversations WHERE id = %s AND lower(user_email) = lower(%s)",
        (conv_id, email),
    )
    if not conv:
        raise HTTPException(status_code=404, detail="conversa não encontrada")
    return conv


@router.get("/conversations")
async def list_conversations(request: Request):
    u = current_user(request)
    if not u.email:
        raise HTTPException(status_code=401, detail="não autenticado")
    return db.query(
        """
        SELECT c.id, c.title, c.created_at, c.updated_at,
               (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS n_messages
        FROM conversations c
        WHERE lower(c.user_email) = lower(%s)
        ORDER BY c.updated_at DESC
        LIMIT 100
        """,
        (u.email,),
    )


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: int, request: Request):
    u = current_user(request)
    if not u.email:
        raise HTTPException(status_code=401, detail="não autenticado")
    conv = _own_conversation(conv_id, u.email)
    msgs = db.query(
        "SELECT id, role, content, transcript, created_at FROM messages WHERE conversation_id = %s ORDER BY created_at",
        (conv_id,),
    )
    return {"conversation": conv, "messages": msgs}


@router.patch("/conversations/{conv_id}")
async def rename_conversation(conv_id: int, body: RenameIn, request: Request):
    u = current_user(request)
    if not u.email:
        raise HTTPException(status_code=401, detail="não autenticado")
    _own_conversation(conv_id, u.email)
    row = db.execute(
        "UPDATE conversations SET title = %s, updated_at = updated_at WHERE id = %s RETURNING id, title",
        (body.title.strip(), conv_id),
    )
    return row


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: int, request: Request):
    u = current_user(request)
    if not u.email:
        raise HTTPException(status_code=401, detail="não autenticado")
    _own_conversation(conv_id, u.email)
    db.execute("DELETE FROM conversations WHERE id = %s", (conv_id,))
    return {"deleted": conv_id}


@router.post("/chat")
async def chat(body: ChatIn, request: Request):
    u = current_user(request)
    if not u.email:
        raise HTTPException(status_code=401, detail="não autenticado")

    # conversa (cria se não veio id)
    if body.conversation_id:
        _own_conversation(body.conversation_id, u.email)
        conv_id = body.conversation_id
    else:
        title = body.prompt.strip()[:60] + ("…" if len(body.prompt.strip()) > 60 else "")
        row = db.execute(
            "INSERT INTO conversations (user_email, title) VALUES (%s, %s) RETURNING id",
            (u.email, title),
        )
        conv_id = row["id"]

    # histórico (turnos anteriores, só user/assistant)
    history = db.query(
        "SELECT role, content FROM messages WHERE conversation_id = %s ORDER BY created_at",
        (conv_id,),
    )

    # grava a mensagem do usuário
    db.execute(
        "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', %s)",
        (conv_id, body.prompt),
    )

    # roda o agente com contexto
    from server.agent_mcp import run_agent_mcp
    try:
        result = await run_agent_mcp(body.prompt, u.email, history=history)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}") from e

    answer = result.get("answer") or ""
    transcript = result.get("transcript") or []

    # grava a resposta do assistant + atualiza a conversa
    msg = db.execute(
        "INSERT INTO messages (conversation_id, role, content, transcript) VALUES (%s, 'assistant', %s, %s) RETURNING id, created_at",
        (conv_id, answer, json.dumps(transcript, default=str)),
    )
    db.execute("UPDATE conversations SET updated_at = now() WHERE id = %s", (conv_id,))

    return {
        "conversation_id": conv_id,
        "message_id": msg["id"] if msg else None,
        "answer": answer,
        "transcript": transcript,
    }
