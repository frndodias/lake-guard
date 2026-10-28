# 🛡️ Lakeguard

Governança e monitoramento de **criação de assets** no Databricks. Controla, de
forma customizada, o que cada usuário/grupo pode criar (dashboards, Genie spaces,
jobs, warehouses, etc.) — algo que os entitlements nativos não fazem de forma
granular.

## Como funciona — defesa em 2 camadas

| Camada | Mecanismo | O que cobre |
|--------|-----------|-------------|
| **Preventiva** | A app é um *gateway*: cria o asset via **on-behalf-of** só se o principal tiver permissão na tabela de roles. | Tudo que passa pelo caminho oficial. |
| **Detectiva** | Job lê `system.access.audit`, cruza com as permissões e gera **alertas** sobre quem criou algo direto na UI sem permissão. | Quem burla o gateway. |

> A camada detectiva tem latência de minutos (audit log) — é **near real-time**.

## Escopo: account inteira

A detecção cobre **todos os workspaces da account** (`system.access.audit` é
account-wide); a UI filtra por workspace. Permissões podem valer para a account
inteira (`workspace_id = '*'`) ou para um workspace específico — o escopo do
workspace tem prioridade sobre o `'*'`.

Limitações (a app roda e tem credencial só no workspace onde está deployada):
- **Usuários**: SCIM do workspace da app + principais vistos no audit (listar a
  account toda exigiria account admin).
- **Grupos**: só são resolvidos os visíveis no workspace da app.
- **Remediar** e **Criar asset**: só no workspace da app; nos demais o alerta
  aponta o workspace para tratamento manual.
- **Nomes de workspace**: vêm de `system.access.workspaces_latest` (se não
  estiver habilitada, a UI mostra o id).

## Estrutura

```
lakeguard/
├── app/                  # Databricks App — FastAPI + React (Vite/TS/Tailwind)
│   ├── app.py            # API + serve SPA
│   ├── app.yaml          # config de runtime (warehouse, lakebase, genie)
│   ├── server/           # config, auth (OBO), db (Lakebase), services, routes/
│   └── frontend/         # UI React (tema Databricks + menu lateral)
├── jobs/                 # DABs bundle do motor de detecção
│   └── detection/detect_violations.py
├── sql/
│   ├── uc_lakeguard.sql       # schema + view sobre system.access.audit (Delta)
│   └── lakebase_schema.sql    # tabelas operacionais (Postgres)
└── setup/provision.md    # passo a passo de provisionamento
```

## Arquitetura de dados

- **Delta / system tables** (`fc_catalog.lakeguard.v_creation_events`): eventos de
  criação lidos direto de `system.access.audit`. Fonte do dashboard e do Genie.
- **Lakebase (Postgres, `lakeguard`)**: estado operacional — capacidades, grants,
  alertas e checkpoint da detecção. Baixa latência para a UI.

## Setup

Ver [setup/provision.md](setup/provision.md). Resumo:

```bash
# 1. UC (schema + view)      -> sql/uc_lakeguard.sql
# 2. Lakebase (instância + schema) -> sql/lakebase_schema.sql
# 3. Genie space (opcional)  -> anotar GENIE_SPACE_ID
# 4. App                     -> build frontend + databricks apps deploy
# 5. Job de detecção         -> cd jobs && databricks bundle deploy -t fevm-fc
```

## Dev local

```bash
export DATABRICKS_PROFILE=fevm-fc
cd app/frontend && npm install && npm run build && cd ..
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
# frontend em watch: cd frontend && npm run dev  (proxy /api -> :8000)
```

Workspace: `fevm-fc` · Catálogo: `fc_catalog` · Schema: `lakeguard`
