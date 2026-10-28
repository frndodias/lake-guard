# Lakeguard — Provisionamento

Profile: **`fevm-fc`** · Workspace: `https://fevm-fc.cloud.databricks.com`
Catálogo: **`fc_catalog`** · Schema UC: **`lakeguard`** · Lakebase: **`lakeguard`**

Ordem de execução. Rode a partir da raiz `lakeguard/`.

## 1. Unity Catalog (schema + view sobre o audit)

```bash
databricks experimental aitools tools query "$(cat sql/uc_lakeguard.sql)" --profile fevm-fc
```
> Alternativa: cole o conteúdo no SQL editor do workspace e execute.

Valide:
```bash
databricks experimental aitools tools query \
  "SELECT capability, COUNT(*) n FROM fc_catalog.lakeguard.v_creation_events \
   WHERE event_date >= current_date() - INTERVAL 7 DAYS GROUP BY capability ORDER BY n DESC" \
  --profile fevm-fc
```

## 2. Lakebase (instância Postgres `lakeguard`)

```bash
# cria a instância (capacidade mínima; ajuste conforme necessário)
databricks database create-database-instance --json '{
  "name": "lakeguard",
  "capacity": "CU_1"
}' --profile fevm-fc

# aguarde ficar AVAILABLE
databricks database get-database-instance lakeguard --profile fevm-fc -o json | grep state
```

Crie o banco `lakeguard` e aplique o schema. Gere a credencial e conecte via `psql`:

```bash
HOST=$(databricks database get-database-instance lakeguard --profile fevm-fc -o json | python3 -c "import sys,json;print(json.load(sys.stdin)['read_write_dns'])")
TOKEN=$(databricks database generate-database-credential --json '{"instance_names":["lakeguard"]}' --profile fevm-fc -o json | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
USER=$(databricks current-user me --profile fevm-fc -o json | python3 -c "import sys,json;print(json.load(sys.stdin)['userName'])")

# cria o database (uma vez), conectando ao 'databricks_postgres' default
PGPASSWORD="$TOKEN" psql "host=$HOST port=5432 dbname=databricks_postgres user=$USER sslmode=require" \
  -c "CREATE DATABASE lakeguard;"

# aplica o schema operacional
PGPASSWORD="$TOKEN" psql "host=$HOST port=5432 dbname=lakeguard user=$USER sslmode=require" \
  -f sql/lakebase_schema.sql
```

## 3. Genie space (agente text-to-SQL) — opcional

Crie um Genie space apontando para `fc_catalog.lakeguard.v_creation_events`
(e, se quiser, tabelas do Lakebase via synced tables). Anote o `space_id` e
coloque em `app/app.yaml` (`GENIE_SPACE_ID`).

## 4. App (build do frontend + deploy)

```bash
# build do frontend
cd app/frontend && npm install && npm run build && cd ../..

# cria e faz deploy da app
databricks apps create lakeguard --profile fevm-fc
databricks sync ./app "/Workspace/Users/fernando.custodio@databricks.com/lakeguard/app" --profile fevm-fc
databricks apps deploy lakeguard \
  --source-code-path "/Workspace/Users/fernando.custodio@databricks.com/lakeguard/app" \
  --profile fevm-fc
```

Na UI da app (Settings → Resources), vincule:
- **SQL warehouse** com o nome de resource `sql-warehouse` (o `app.yaml` referencia).
- **Database (Lakebase)** `lakeguard` — injeta `PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD`.

Habilite **User authorization** (OBO) com os escopos `sql`, `dashboards.genie`
para o gateway de criação funcionar com a identidade do usuário.

Dê ao **service principal da app** permissão de leitura em `system.access.audit`
e no schema `fc_catalog.lakeguard`, e workspace-admin (ou entitlement SCIM) para
listar usuários/grupos.

## 5. Job de detecção (DABs)

```bash
cd jobs
databricks bundle validate -t fevm-fc --profile fevm-fc
databricks bundle deploy  -t fevm-fc --profile fevm-fc
databricks bundle run lakeguard_detection -t fevm-fc --profile fevm-fc   # execução manual
```

O job roda a cada 10 min e popula a tabela `alerts` no Lakebase.
```
