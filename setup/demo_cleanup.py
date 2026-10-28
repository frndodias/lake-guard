"""Remove o ambiente de demo criado por setup/demo_seed.py.

Apaga: catalogs lg_*, grupos dbdemo-*, usuários dbdemo.*@nuvemshop.example, SPs dbdemo-sp-*
e os dados do schema lg no Lakebase (o schema e as tabelas ficam).

Uso:  ~/dev/lg-venv/bin/python setup/demo_cleanup.py --yes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "setup"))

from databricks.sdk import WorkspaceClient  # noqa: E402

from demo_seed import CATALOG_MAP, PFX, PROFILE, lakebase_conn  # noqa: E402
from server import identity as idn  # noqa: E402

LG_TABLES = ["alerts", "action_log", "manual_members", "migration_waves", "migration_mappings", "change_requests",
             "inv_usage", "inv_creations", "inv_permission_events", "inv_grants", "inv_closure", "inv_memberships",
             "inv_securables", "inv_principals", "persona_versions", "persona_capabilities", "persona_grants",
             "personas", "app_roles", "domains", "capabilities", "catalogs", "settings"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="confirma a remoção")
    args = ap.parse_args()
    if not args.yes:
        print("Rode com --yes para remover o ambiente de demo.")
        return
    w = WorkspaceClient(profile=PROFILE)
    for logical, cat in CATALOG_MAP.items():
        if cat.startswith("lg_"):
            try:
                w.catalogs.delete(cat, force=True)
                print(f"catalog {cat} removido")
            except Exception as ex:  # noqa: BLE001
                print(f"catalog {cat}: {ex}")
    for g in idn.list_groups(w, f'displayName sw "{PFX}"'):
        idn.delete(w, "Groups", g["id"])
        print(f"grupo {g['displayName']} removido")
    for u in idn.list_users(w, 'userName sw "dbdemo."'):
        if u["userName"].endswith("@nuvemshop.example"):
            idn.delete(w, "Users", u["id"])
            print(f"usuário {u['userName']} removido")
    res = w.api_client.do("GET", f"{idn.BASE}/ServicePrincipals",
                          query={"filter": f'displayName sw "{PFX}sp-"', "count": 100})
    for sp in res.get("Resources") or []:
        idn.delete(w, "ServicePrincipals", sp["id"])
        print(f"SP {sp['displayName']} removido")
    conn = lakebase_conn(w)
    with conn.cursor() as cur:
        for t in LG_TABLES:
            cur.execute(f"DELETE FROM {t}")
        cur.execute("UPDATE inv_state SET last_run_at = NULL, status = NULL, error = NULL, counts = NULL")
    conn.commit()
    conn.close()
    print("Lakebase (schema lg) limpo. O app recarrega o modelo do documento no próximo start.")


if __name__ == "__main__":
    main()
