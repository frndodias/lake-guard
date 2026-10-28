"""Controle de acesso do PRÓPRIO app.

Papéis (tabela app_roles, por usuário ou grupo):
  admin   — configura personas, aprova mudanças estruturais, gerencia o app
  steward — aprova pedidos de acesso do seu domínio
  dpo     — segunda aprovação para domínios críticos (RH, fintech, PII)
  auditor — leitura de tudo, sem alterar
Sem papel: pode pedir acesso e ver o próprio acesso.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request

from server import db
from server.auth import current_user
from server.config import BOOTSTRAP_ADMINS, IS_DATABRICKS_APP, LOCAL_DEV_EMAIL, get_workspace_client


@dataclass
class UserCtx:
    email: str
    name: str
    initials: str
    token: str | None
    roles: list[dict] = field(default_factory=list)

    def has(self, role: str) -> bool:
        return any(r["role"] == role for r in self.roles)

    @property
    def is_admin(self) -> bool:
        return self.has("admin")

    @property
    def is_dpo(self) -> bool:
        return self.has("dpo")

    @property
    def is_auditor(self) -> bool:
        return self.has("auditor")

    @property
    def steward_domains(self) -> list[str]:
        return sorted({r["domain"] for r in self.roles if r["role"] == "steward" and r["domain"]})

    def is_steward(self, domain: str | None) -> bool:
        return bool(domain) and domain in self.steward_domains

    @property
    def can_view(self) -> bool:
        return self.is_admin or self.is_dpo or self.is_auditor or bool(self.steward_domains)

    def public(self) -> dict:
        return {"email": self.email, "name": self.name, "initials": self.initials,
                "roles": self.roles, "is_admin": self.is_admin, "is_dpo": self.is_dpo,
                "is_auditor": self.is_auditor, "steward_domains": self.steward_domains, "can_view": self.can_view}


_groups_cache: dict[str, tuple[float, list[str]]] = {}
_lock = threading.Lock()


def _user_groups(email: str) -> list[str]:
    with _lock:
        hit = _groups_cache.get(email)
        if hit and time.time() - hit[0] < 120:
            return hit[1]
    groups: list[str] = []
    try:
        matches = list(get_workspace_client().users.list(filter=f'userName eq "{email}"', attributes="groups"))
        if matches:
            groups = [g.display for g in (matches[0].groups or []) if g.display]
    except Exception:  # noqa: BLE001
        groups = []
    with _lock:
        _groups_cache[email] = (time.time(), groups)
    return groups


def load_roles(email: str) -> list[dict]:
    names = [email.lower()] + [g.lower() for g in _user_groups(email)]
    rows = db.query("SELECT role, domain, principal, principal_type FROM app_roles WHERE lower(principal) = ANY(%s)",
                    (names,))
    roles = [{"role": r["role"], "domain": r["domain"], "via": r["principal"]} for r in rows]
    if email.lower() in BOOTSTRAP_ADMINS and not any(r["role"] == "admin" for r in roles):
        roles.append({"role": "admin", "domain": None, "via": "bootstrap"})
    return roles


def get_user(request: Request) -> UserCtx:
    cu = current_user(request)
    email = cu.email or (None if IS_DATABRICKS_APP else LOCAL_DEV_EMAIL)
    if not email:
        raise HTTPException(status_code=401, detail="usuário não identificado")
    name = cu.name if cu.email else email.split("@")[0].replace(".", " ").title()
    initials = "".join(p[0] for p in name.split()[:2]).upper() or "?"
    return UserCtx(email=email, name=name, initials=initials, token=cu.token, roles=load_roles(email))


def require_view(user: UserCtx = Depends(get_user)) -> UserCtx:
    if not user.can_view:
        raise HTTPException(status_code=403, detail="sem papel no Lakeguard (admin, steward, DPO ou auditor)")
    return user


def require_admin(user: UserCtx = Depends(get_user)) -> UserCtx:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="apenas admin do Lakeguard")
    return user
