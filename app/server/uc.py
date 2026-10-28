"""Unity Catalog: GRANTs (REST de permissions) e listagem de objetos.

Usa a API REST direto (`/api/2.1/unity-catalog/permissions/...`) para não
depender de enums do SDK que mudam entre versões. Privilégios no formato
da API: USE_CATALOG, SELECT, ALL_PRIVILEGES…
"""

from __future__ import annotations

from urllib.parse import quote

from databricks.sdk import WorkspaceClient

PERM = "/api/2.1/unity-catalog/permissions"


def _path(sec_type: str, full_name: str) -> str:
    return f"{PERM}/{sec_type.lower()}/{quote(full_name, safe='')}"


def get_grants(w: WorkspaceClient, sec_type: str, full_name: str) -> list[dict]:
    """[{principal, privileges:[...]}] — só os GRANTs diretos no objeto."""
    res = w.api_client.do("GET", _path(sec_type, full_name))
    return [
        {"principal": a["principal"], "privileges": list(a.get("privileges") or [])}
        for a in (res.get("privilege_assignments") or [])
    ]


def update_grants(w: WorkspaceClient, sec_type: str, full_name: str, principal: str,
                  add: list[str] | None = None, remove: list[str] | None = None) -> None:
    change: dict = {"principal": principal}
    if add:
        change["add"] = add
    if remove:
        change["remove"] = remove
    w.api_client.do("PATCH", _path(sec_type, full_name), body={"changes": [change]})


def list_schemas(w: WorkspaceClient, catalog: str) -> list[dict]:
    out = []
    for s in w.schemas.list(catalog_name=catalog):
        if s.name in ("information_schema",):
            continue
        out.append({"name": s.name, "full_name": s.full_name, "owner": s.owner,
                    "created_by": getattr(s, "created_by", None), "created_at": getattr(s, "created_at", None)})
    return out


def list_tables(w: WorkspaceClient, catalog: str, schema: str) -> list[dict]:
    out = []
    for t in w.tables.list(catalog_name=catalog, schema_name=schema):
        ttype = (t.table_type.value if t.table_type else "TABLE").upper()
        out.append({"name": t.name, "full_name": t.full_name, "owner": t.owner,
                    "type": "view" if "VIEW" in ttype else "table",
                    "created_by": t.created_by, "created_at": t.created_at})
    return out


def get_catalog(w: WorkspaceClient, name: str) -> dict | None:
    try:
        c = w.catalogs.get(name)
    except Exception:  # noqa: BLE001
        return None
    return {"name": c.name, "owner": c.owner, "created_by": getattr(c, "created_by", None),
            "created_at": getattr(c, "created_at", None)}


def q(name: str) -> str:
    """Nome com crase por parte: a.b.c → `a`.`b`.`c`."""
    return ".".join(f"`{p}`" for p in name.split("."))


def priv_sql(p: str) -> str:
    return p.replace("_", " ")


def grant_sql(sec_type: str, full_name: str, principal: str, privileges: list[str], revoke: bool = False) -> str:
    privs = ", ".join(priv_sql(p) for p in privileges)
    kw = "REVOKE" if revoke else "GRANT"
    prep = "FROM" if revoke else "TO"
    return f"{kw} {privs} ON {sec_type.upper()} {q(full_name)} {prep} `{principal}`;"
