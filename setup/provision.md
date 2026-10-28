# Lakeguard — Provisionamento

Profile: **`fevm-fc`** · Workspace: `https://fevm-fc.cloud.databricks.com`
Lakebase: instância **`lakeguard`**, database `lakeguard`, schema **`lg`** · UC: `fc_catalog.lakeguard`

Rode a partir da raiz `lakeguard/`.

## 1. Lakebase (schema lg)

```bash
HOST=$(databricks database get-database-instance lakeguard -p fevm-fc -o json | jq -r .read_write_dns)
TOKEN=$(databricks database generate-database-credential --json '{"instance_names":["lakeguard"]}' -p fevm-fc -o json | jq -r .token)
USER=$(databricks current-user me -p fevm-fc -o json | jq -r .userName)
PGPASSWORD="$TOKEN" psql "host=$HOST port=5432 dbname=lakeguard user=$USER sslmode=require" -f sql/lakebase_schema.sql
```

Depois, dê ao role do SP do app (client_id) acesso ao schema — ver o bloco comentado no fim de
`sql/lakebase_schema.sql`. Re-vincular o resource de database recria o role: reaplique os GRANTs.

## 2. Permissões do SP do app

| Onde | O quê | Por quê |
|------|-------|---------|
| Catalogs do modelo | `USE CATALOG`, `USE SCHEMA`, `BROWSE`, `MANAGE` | listar objetos e aplicar GRANT/REVOKE |
| Grupos do modelo (conta) | papel `group.manager` | adicionar/remover membros (pedidos, migração) |
| Job de inventário | `CAN_MANAGE_RUN` | botão "Rodar agora" |
| Lakebase `lg` | USAGE + DML | estado do app |

Sem account admin, o SP só gerencia grupos onde for group manager. Ler o SCIM de conta (via
`/api/2.0/account/scim/v2` no host do workspace) funciona para qualquer usuário.

## 3. Ambiente de demo (opcional)

```bash
~/dev/lg-venv/bin/python setup/demo_seed.py        # cria lg_*, dbdemo-*, GRANTs e o modelo
~/dev/lg-venv/bin/python setup/demo_cleanup.py --yes   # remove tudo
```

Para um cliente real: ajuste em **Administração** os catalogs lógicos → físicos, o prefixo de
grupos (vazio), o filtro de escopo SCIM e a chave da tag de sensibilidade; desligue `demo_mode`
e `allow_self_approval`.

## 4. Job de inventário (DABs, raiz do repo)

```bash
databricks bundle deploy -p fevm-fc
databricks bundle run lakeguard_inventory -p fevm-fc
```

Atualize `INVENTORY_JOB_ID` em `app/app.yaml` com o id do job.

## 5. App

```bash
cd app/frontend && npm install && npm run build && cd ..
databricks sync . /Workspace/Users/fernando.custodio@databricks.com/lakeguard/app \
  --include "frontend/dist/**" --exclude "frontend/node_modules/**" --exclude "frontend/src/**" -p fevm-fc
databricks apps deploy lakeguard --source-code-path /Workspace/Users/fernando.custodio@databricks.com/lakeguard/app -p fevm-fc
```

Resources do app: `sql-warehouse` (não usar warehouse REALTIME) e `lakebase` (Database Instance).

## Dev local

```bash
cd app && LAKEGUARD_PG_SCHEMA=lg WAREHOUSE_ID=<id> ~/dev/lg-venv/bin/uvicorn app:app --port 8001
```

Sem os headers do Databricks Apps, o usuário local é `LAKEGUARD_LOCAL_EMAIL`.
