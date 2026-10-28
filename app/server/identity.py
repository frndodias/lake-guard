"""Identidades de nível de CONTA via proxy SCIM do workspace.

`/api/2.0/account/scim/v2/*` no host do workspace dá acesso aos grupos, usuários
e service principals da conta sem precisar de credencial de account console.
Ler funciona para qualquer usuário; alterar membros exige ser group manager
(ou account admin).
"""

from __future__ import annotations

from typing import Any, Iterator

from databricks.sdk import WorkspaceClient

BASE = "/api/2.0/account/scim/v2"
PATCH_SCHEMA = ["urn:ietf:params:scim:api:messages:2.0:PatchOp"]


def _get(w: WorkspaceClient, path: str, query: dict | None = None) -> dict:
    return w.api_client.do("GET", f"{BASE}/{path}", query=query or {})


def _paged(w: WorkspaceClient, path: str, query: dict) -> Iterator[dict]:
    start, count = 1, 100
    while True:
        page = _get(w, path, {**query, "startIndex": start, "count": count})
        res = page.get("Resources") or []
        yield from res
        total = int(page.get("totalResults") or 0)
        start += len(res)
        if not res or start > total:
            return


def member_type(ref: str | None) -> str:
    ref = (ref or "").lower()
    if "groups/" in ref:
        return "group"
    if "serviceprincipals/" in ref:
        return "sp"
    return "user"


def list_groups(w: WorkspaceClient, scim_filter: str | None = None) -> list[dict]:
    q: dict[str, Any] = {"attributes": "id,displayName,members"}
    if scim_filter:
        q["filter"] = scim_filter
    return list(_paged(w, "Groups", q))


def get_group(w: WorkspaceClient, gid: str) -> dict:
    return _get(w, f"Groups/{gid}")


def find_group(w: WorkspaceClient, name: str) -> dict | None:
    res = _get(w, "Groups", {"filter": f'displayName eq "{name}"', "attributes": "id,displayName,members"})
    items = res.get("Resources") or []
    return items[0] if items else None


def get_user(w: WorkspaceClient, uid: str) -> dict:
    return _get(w, f"Users/{uid}", {"attributes": "id,userName,displayName,active"})


def find_user(w: WorkspaceClient, user_name: str) -> dict | None:
    res = _get(w, "Users", {"filter": f'userName eq "{user_name}"', "attributes": "id,userName,displayName,active"})
    items = res.get("Resources") or []
    return items[0] if items else None


def list_users(w: WorkspaceClient, scim_filter: str) -> list[dict]:
    return list(_paged(w, "Users", {"filter": scim_filter, "attributes": "id,userName,displayName,active"}))


def get_sp(w: WorkspaceClient, sid: str) -> dict:
    return _get(w, f"ServicePrincipals/{sid}", {"attributes": "id,applicationId,displayName,active"})


def find_sp(w: WorkspaceClient, app_id: str) -> dict | None:
    res = _get(w, "ServicePrincipals", {"filter": f'applicationId eq "{app_id}"',
                                         "attributes": "id,applicationId,displayName,active"})
    items = res.get("Resources") or []
    return items[0] if items else None


def find_sp_by_name(w: WorkspaceClient, display_name: str) -> dict | None:
    res = _get(w, "ServicePrincipals", {"filter": f'displayName eq "{display_name}"',
                                         "attributes": "id,applicationId,displayName,active"})
    items = res.get("Resources") or []
    return items[0] if items else None


def add_member(w: WorkspaceClient, group_id: str, member_id: str) -> None:
    w.api_client.do("PATCH", f"{BASE}/Groups/{group_id}", body={
        "schemas": PATCH_SCHEMA,
        "Operations": [{"op": "add", "path": "members", "value": [{"value": str(member_id)}]}],
    })


def remove_member(w: WorkspaceClient, group_id: str, member_id: str) -> None:
    w.api_client.do("PATCH", f"{BASE}/Groups/{group_id}", body={
        "schemas": PATCH_SCHEMA,
        "Operations": [{"op": "remove", "path": f'members[value eq "{member_id}"]'}],
    })


def create_group(w: WorkspaceClient, name: str) -> dict:
    return w.api_client.do("POST", f"{BASE}/Groups", body={
        "displayName": name, "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"]})


def create_user(w: WorkspaceClient, user_name: str, display_name: str) -> dict:
    return w.api_client.do("POST", f"{BASE}/Users", body={
        "userName": user_name, "displayName": display_name, "active": True,
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"]})


def set_user_active(w: WorkspaceClient, uid: str, active: bool) -> None:
    w.api_client.do("PATCH", f"{BASE}/Users/{uid}", body={
        "schemas": PATCH_SCHEMA,
        "Operations": [{"op": "replace", "path": "active", "value": active}]})


def create_sp(w: WorkspaceClient, display_name: str) -> dict:
    return w.api_client.do("POST", f"{BASE}/ServicePrincipals", body={
        "displayName": display_name, "active": True,
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServicePrincipal"]})


def delete(w: WorkspaceClient, kind: str, rid: str) -> None:
    w.api_client.do("DELETE", f"{BASE}/{kind}/{rid}")


def add_group_managers(w: WorkspaceClient, account_id: str, group_id: str, principals: list[str]) -> None:
    """Garante principals (ex.: 'servicePrincipals/<appId>') no papel group.manager do grupo."""
    name = f"accounts/{account_id}/groups/{group_id}/ruleSets/default"
    rs = w.api_client.do("GET", "/api/2.0/preview/accounts/access-control/rule-sets",
                         query={"name": name, "etag": ""})
    rules = rs.get("grant_rules") or []
    mgr = next((r for r in rules if r.get("role") == "roles/group.manager"), None)
    if mgr is None:
        mgr = {"role": "roles/group.manager", "principals": []}
        rules.append(mgr)
    missing = [p for p in principals if p not in mgr["principals"]]
    if not missing:
        return
    mgr["principals"] += missing
    w.api_client.do("PUT", "/api/2.0/preview/accounts/access-control/rule-sets", body={
        "name": name, "rule_set": {"name": name, "etag": rs.get("etag"), "grant_rules": rules}})
