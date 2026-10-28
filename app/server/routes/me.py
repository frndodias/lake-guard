"""Usuário logado."""

from fastapi import APIRouter, Request

from server.auth import current_user

router = APIRouter(prefix="/api")


@router.get("/me")
async def get_me(request: Request):
    u = current_user(request)
    return {
        "email": u.email,
        "name": u.name,
        "initials": u.initials,
        "authenticated": u.is_authenticated,
    }
