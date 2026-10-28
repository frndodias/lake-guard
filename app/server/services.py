"""Regras de negócio compartilhadas — resolução de permissões efetivas."""

from __future__ import annotations

from server import db
from server.config import get_workspace_client


def user_groups(email: str) -> list[str]:
    """Nomes dos grupos do usuário (via SCIM). Vazio se não encontrado."""
    w = get_workspace_client()
    matches = list(w.users.list(filter=f'userName eq "{email}"'))
    if not matches:
        return []
    return [g.display for g in (matches[0].groups or []) if g.display]


def effective_permissions(
    email: str, groups: list[str] | None = None, workspace_id: str | None = None
) -> dict[str, dict]:
    """Permissão efetiva por capacidade para um usuário em um workspace.

    workspace_id=None avalia só as concessões da account inteira ('*').
    Precedência (igual ao job de detecção): escopo do workspace > '*'; dentro
    do escopo, negação > concessão; sem concessão = negado.
    Concessões batem tanto no e-mail (user) quanto nos grupos do usuário.
    """
    groups = groups if groups is not None else user_groups(email)
    principals = [email] + groups
    scopes = ["*"] if workspace_id is None else ["*", workspace_id]

    caps = db.query(
        "SELECT code, label, default_severity, enabled FROM capabilities ORDER BY label"
    )
    grants = db.query(
        """
        SELECT principal, principal_type, capability, workspace_id, allowed
        FROM grants
        WHERE lower(principal) = ANY(%s) AND workspace_id = ANY(%s)
        """,
        ([p.lower() for p in principals], scopes),
    )

    by_cap: dict[str, list[dict]] = {}
    for g in grants:
        by_cap.setdefault(g["capability"], []).append(g)

    result: dict[str, dict] = {}
    for cap in caps:
        code = cap["code"]
        all_rows = by_cap.get(code, [])
        rows = [r for r in all_rows if r["workspace_id"] == workspace_id] or [
            r for r in all_rows if r["workspace_id"] == "*"
        ]
        denied = any(not r["allowed"] for r in rows)
        allowed = any(r["allowed"] for r in rows)
        source = None
        if rows:
            # fonte = quem concedeu/negou (prioriza o user sobre o grupo)
            user_row = next((r for r in rows if r["principal_type"] == "user"), None)
            source = (user_row or rows[0])
        result[code] = {
            "capability": code,
            "label": cap["label"],
            "allowed": bool(allowed and not denied),
            "denied": denied,
            "source_principal": source["principal"] if source else None,
            "source_type": source["principal_type"] if source else None,
            "source_workspace": source["workspace_id"] if source else None,
        }
    return result
