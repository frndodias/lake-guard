"""Identidade do usuário logado (headers injetados pelo Databricks Apps)."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request


@dataclass
class CurrentUser:
    email: str | None
    name: str
    initials: str
    token: str | None  # x-forwarded-access-token (para OBO no gateway)

    @property
    def is_authenticated(self) -> bool:
        return bool(self.email)


def _name_from_email(email: str) -> str:
    local = email.split("@")[0]
    return " ".join(p.capitalize() for p in local.replace("_", ".").split("."))


def _initials(name: str) -> str:
    parts = name.strip().split()
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def current_user(request: Request) -> CurrentUser:
    """Extrai o usuário dos headers forward do Databricks Apps.

    Localmente esses headers não existem — retorna um usuário "dev".
    """
    email = (
        request.headers.get("x-forwarded-email")
        or request.headers.get("x-forwarded-preferred-username")
        or None
    )
    token = request.headers.get("x-forwarded-access-token")
    name = _name_from_email(email) if email else "Dev (local)"
    return CurrentUser(email=email, name=name, initials=_initials(name), token=token)
