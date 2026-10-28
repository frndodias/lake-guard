"""Modelo de personas da Nuvemshop (documento "Personas e Acessos no Databricks").

Fonte do seed do estado DESEJADO. Os nomes de catalog aqui são LÓGICOS
(raw, data_products_prd…); o mapeamento para os catalogs físicos fica na
tabela `catalogs` (ex.: raw → lg_raw no ambiente de demo).

schema_scope: None = catalog inteiro · '@staging' = schema data_staging ·
'@product' = todos os schemas de domínio do catalog (exceto staging).
"""

from __future__ import annotations

STAGING_SCHEMA = "data_staging"

# (logical_name, layer, env, description, managed, sort)
CATALOGS = [
    ("data_products_prd", "product", "prd", "Catalog analítico principal (staging + domínios)", True, 10),
    ("data_products_dev", "dev", "dev", "Desenvolvimento e iteração de AE", True, 20),
    ("raw", "raw", "prd", "Zona de landing (cópias dos sistemas de origem)", True, 30),
    ("ds_catalog", "ds", "dev", "Área de experimentação de data science", True, 40),
    ("ds_outputs_prd", "ds", "prd", "Outputs publicados de data science", True, 50),
    ("ds_outputs_dev", "ds", "dev", "Outputs de desenvolvimento de data science", True, 60),
    ("sandbox", "sandbox", "dev", "Experimentação descartável", True, 70),
    ("billing_data", "billing", "prd", "Dados financeiros sensíveis", True, 80),
    ("system", "system", "n/a", "System tables (auditoria e linhagem)", False, 90),
]

READ = ["USE_CATALOG", "USE_SCHEMA", "SELECT"]
CREATE = ["USE_CATALOG", "USE_SCHEMA", "CREATE_TABLE"]

# code, label, category, description, sort
PERSONAS = [
    ("platform-admin", "Data Platform Admin", "Platform",
     "Equipe da conta, workspaces, rede, operações de UC e custos. Ajustado à recomendação: "
     "administra (BROWSE + MANAGE) sem ler dados por padrão; acesso a dados via break-glass "
     "com prazo (o documento original prevê ALL PRIVILEGES).", 10),
    ("data-engineer", "Data Engineer", "Creator",
     "Pipelines batch/stream, ingestão e Spark. Lê raw + staging + product e escreve em dev.", 20),
    ("analytics-engineer", "Analytics Engineer & Analytics", "Creator",
     "Camada semântica, métricas e dbt. Mesma leitura do engineer; cluster só compartilhado.", 30),
    ("data-scientist", "Data Scientist", "Creator",
     "Feature engineering, treino e experimentos. Leitura completa, escrita em dev de DS, GPU.", 40),
    ("mlops", "MLOps", "Platform",
     "Deploy, serving e monitoramento de modelos. Lê raw até product e catalogs de DS.", 50),
    ("sql-explorer", "SQL Explorer", "Explorer",
     "Analistas de SQL. Lê staging + product (GRANT por schema); cria tabelas só no sandbox.", 60),
    ("data-explorer", "Guided Explorer, Dashboard Consumer, Data Extractor", "Explorer",
     "Usuários de negócio: dashboards, Genie e extratos. Lê só a camada product.", 70),
    ("data-steward", "Data Steward", "Conductor",
     "Governança de domínio: lê staging + product, sem escrita. Recomendação: tratar como papel "
     "adicional por domínio (aprovador), não como persona exclusiva.", 80),
    ("data-observer", "Viewer & Report Subscriber", "Consumer",
     "Consome dashboards e assinaturas. Só BROWSE (descoberta de metadados).", 90),
]

ALL_CATALOGS = [c[0] for c in CATALOGS]

# persona -> [(catalog_logical, schema_scope, privileges)]   (§6.2 + §6.4)
PERSONA_GRANTS: dict[str, list[tuple[str, str | None, list[str]]]] = {
    "platform-admin": [(c, None, ["USE_CATALOG", "BROWSE", "MANAGE"]) for c in ALL_CATALOGS],
    "data-engineer": [
        ("data_products_prd", None, READ), ("data_products_dev", None, CREATE), ("raw", None, READ),
        ("ds_catalog", None, CREATE), ("ds_outputs_prd", None, READ), ("ds_outputs_dev", None, CREATE),
        ("sandbox", None, CREATE), ("billing_data", None, READ), ("system", None, ["USE_CATALOG"]),
    ],
    "analytics-engineer": [
        ("data_products_prd", None, READ), ("data_products_dev", None, CREATE), ("raw", None, READ),
        ("ds_catalog", None, CREATE), ("ds_outputs_prd", None, READ), ("ds_outputs_dev", None, CREATE),
        ("sandbox", None, CREATE), ("billing_data", None, READ), ("system", None, ["USE_CATALOG"]),
    ],
    "data-scientist": [
        ("data_products_prd", None, READ), ("data_products_dev", None, CREATE), ("raw", None, READ),
        ("ds_catalog", None, CREATE), ("ds_outputs_prd", None, READ), ("ds_outputs_dev", None, CREATE),
        ("sandbox", None, CREATE), ("system", None, ["USE_CATALOG"]),
    ],
    "mlops": [
        ("data_products_prd", None, READ), ("data_products_dev", None, CREATE), ("raw", None, READ),
        ("ds_catalog", None, READ), ("ds_outputs_prd", None, READ), ("ds_outputs_dev", None, CREATE),
        ("system", None, ["USE_CATALOG"]),
    ],
    "sql-explorer": [
        ("data_products_prd", None, ["USE_CATALOG", "BROWSE"]),
        ("data_products_prd", "@staging", ["USE_SCHEMA", "SELECT"]),
        ("data_products_prd", "@product", ["USE_SCHEMA", "SELECT"]),
        ("ds_outputs_prd", None, READ),
        ("sandbox", None, CREATE),
    ],
    "data-explorer": [
        ("data_products_prd", None, ["USE_CATALOG", "BROWSE"]),
        ("data_products_prd", "@product", ["USE_SCHEMA", "SELECT"]),
        ("ds_outputs_prd", None, ["BROWSE"]),
    ],
    "data-steward": [
        ("data_products_prd", None, ["USE_CATALOG", "BROWSE"]),
        ("data_products_prd", "@staging", ["USE_SCHEMA", "SELECT"]),
        ("data_products_prd", "@product", ["USE_SCHEMA", "SELECT"]),
    ],
    "data-observer": [
        ("data_products_prd", None, ["BROWSE"]),
        ("ds_outputs_prd", None, ["BROWSE"]),
        ("billing_data", None, ["BROWSE"]),
    ],
}

# capacidades de CRIAÇÃO (mapeadas ao audit log)
CAPABILITIES = [
    ("dashboard", "Dashboard (AI/BI)", "dashboards", ["createDashboard"], "warning"),
    ("genie", "Genie Space", "aibiGenie", ["genieCreateSpace", "createSpace"], "warning"),
    ("job", "Job / Workflow", "jobs", ["create"], "warning"),
    ("pipeline", "Pipeline (Lakeflow)", "pipelines", ["create"], "warning"),
    ("notebook", "Notebook", "notebook", ["createNotebook"], "info"),
    ("warehouse", "SQL Warehouse", "databrickssql", ["createWarehouse"], "critical"),
    ("query", "SQL Query", "databrickssql", ["createQuery"], "info"),
    ("cluster", "Cluster", "clusters", ["create"], "warning"),
    ("model_serving", "Model Serving", "serverlessRealTimeInference", ["createServingEndpoint"], "critical"),
    ("registered_model", "Registered Model (UC)", "unityCatalog", ["createRegisteredModel"], "warning"),
    ("app", "Databricks App", "apps", ["createApp"], "warning"),
]

PERSONA_CAPABILITIES = {
    "platform-admin": [c[0] for c in CAPABILITIES],
    "data-engineer": ["dashboard", "job", "pipeline", "notebook", "query", "cluster"],
    "analytics-engineer": ["dashboard", "genie", "job", "notebook", "query"],
    "data-scientist": ["dashboard", "job", "notebook", "query", "cluster", "registered_model"],
    "mlops": ["job", "notebook", "cluster", "model_serving", "registered_model"],
    "sql-explorer": ["dashboard", "query"],
    "data-explorer": [],
    "data-steward": [],
    "data-observer": [],
}

# domínios (schemas da camada product em data_products_prd)
# code, name, schema, sensitivity, clearance_group
DOMAINS = [
    ("operations", "Operations", "data_operations", "normal", None),
    ("marketing", "Marketing", "data_marketing", "normal", None),
    ("product", "Product", "data_product", "normal", None),
    ("finance", "Finance", "data_finance", "restricted", "clearance-finance"),
    ("fintech", "Fintech", "data_fintech", "critical", "clearance-fintech"),
    ("people", "People (RH)", "data_people", "critical", "clearance-people"),
]

DEFAULT_SETTINGS = {
    "group_prefix": "",                 # demo: "dbdemo-"
    "group_scope_filter": "",           # filtro SCIM de grupos no escopo (vazio = todos)
    "sensitivity_tag_key": "data_sensitivity",
    "demo_mode": False,
    "allow_self_approval": False,
    "clone_group_pattern": "users-clone",
    "system_groups": ["Service-Principals", "mcp-cursor-group", "admins", "users", "account users"],
    "floor_privileges": {"data_products_prd": ["BROWSE"]},
    "app_principals": [],               # applicationId do SP do app (pode ter GRANTs fora do modelo)
    "audit_lookback_days": 7,           # janela do audit (conta inteira = volumoso)
}


def persona_group(code: str) -> str:
    return f"persona-{code}"


def idp_group(code: str) -> str:
    return f"idp-persona-{code}"
