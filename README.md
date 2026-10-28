# 🛡️ Lakeguard

Governança de acessos no Databricks baseada em **modelo de personas**: visão 360 de
quem pode × quem usa, personas como dado (desejado × atual), pedidos de acesso com
prazo e aprovação, migração dos grupos legados em ondas e regras contínuas.

> O Unity Catalog **aplica** as regras · o Lakeguard **organiza e dá visibilidade** ·
> as pessoas **decidem**.

## Módulos

| Tela | O que faz |
|------|-----------|
| **Diagnóstico** | Indicadores (usuários com exatamente 1 persona, % de GRANTs fora do modelo…), matriz principal × catalog e principais anomalias |
| **Visão 360** | Por identidade, grupo ou dado: grupos (inclusive aninhados), acesso efetivo com o caminho (“por quê”), pode × usa, o que criou, rede de acessos |
| **Personas** | As 9 personas do documento como dado: permissões por catalog/schema, membros (IdP aninhado + manuais com prazo), prévia de impacto, aprovação, aplicação, versões e rollback |
| **Domínios e clearance** | Schemas de domínio, sensibilidade (normal / restrito / crítico), grupos `clearance-*` e stewards aprovadores |
| **Solicitações** | Pedir acesso com prazo → steward aprova (+ DPO se crítico) → SP aplica → expira sozinho |
| **Migração** | De-para dos grupos legados (→ persona, → clearance, apagar, → SP, reduzir o clone) e ondas com prévia de impacto e rollback |
| **Regras e alertas** | GRANT fora do modelo, GRANT direto a usuário, escrita humana em produção, dado sensível sem clearance, admin se auto-atribuindo, persona fora do modelo… |
| **Administração** | Papéis do app (admin, steward por domínio, DPO, auditor), catalogs lógicos → físicos, configurações, inventário e trilha de auditoria |

## Arquitetura

```
Usuários (SSO) ──► App Lakeguard (FastAPI + React, Databricks App)
                     │  controle de acesso do app (app_roles)
                     ├─ motor de acesso em memória (grupos aninhados, herança, ownership, simulação)
                     ├─ Lakebase (schema lg): modelo, pedidos, alertas, log + espelho do inventário
                     └─ camada de aplicação: SP do app → GRANT/REVOKE (UC) e membros (SCIM de conta)
Job de inventário (serverless, de hora em hora)
   SCIM de conta + Grants API + system tables (lineage, audit)
   → Lakebase (lg.inv_*) + Delta (fc_catalog.lakeguard.inv_*) → regras → expirações
```

Princípios: **quem decide não executa** (pessoas aprovam, o SP aplica); quem pede não
aprova; acesso temporário entra como **membro de grupo** (`clearance-*`), nunca como GRANT
direto ao usuário; personas recebem GRANT só em domínios **normais e cadastrados**
(domínios restritos/críticos vão para o clearance).

## Estrutura

```
lakeguard/
├── databricks.yml          # bundle do job de inventário (raiz)
├── app/                    # Databricks App
│   ├── app.py, app.yaml
│   ├── server/             # engine, inventory, rules, workflow, executor, migration, rbac, routes/
│   └── frontend/           # React + Vite + Tailwind
├── jobs/inventory/run.py   # job (usa app/server)
├── sql/lakebase_schema.sql # schema lg (Postgres)
└── setup/                  # provision.md, demo_seed.py, demo_cleanup.py
```

## Ambiente de demo (fevm-fc)

`setup/demo_seed.py` simula o cenário da Nuvemshop: catalogs `lg_*`, grupos de conta
`dbdemo-*` (personas, espelhos do IdP, clearance, legados, clone, agentes), 20 usuários
fictícios `dbdemo.*@nuvemshop.example`, 6 SPs `dbdemo-sp-*`, GRANTs bagunçados e uso
simulado. Remoção: `setup/demo_cleanup.py --yes`.

Ver [setup/provision.md](setup/provision.md) para o provisionamento completo.
