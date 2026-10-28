-- =====================================================================
-- Lakeguard — Lakebase (PostgreSQL) operational schema
-- =====================================================================
-- Camada OPERACIONAL (OLTP) da app: capacidades governáveis, concessões
-- por usuário/grupo, alertas de violação e checkpoint do motor de deteccao.
--
-- Os dados ANALÍTICOS (audit log) NÃO ficam aqui — sao lidos direto de
-- system.access.audit via SQL warehouse (ver sql/uc_lakeguard.sql).
--
-- Rode este script uma vez contra o banco `lakeguard` (ver setup/provision.md).
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS lakeguard;
SET search_path TO lakeguard;

-- ---------------------------------------------------------------------
-- capabilities: catálogo das capacidades governáveis + mapeamento para o
-- audit log. É a fonte-da-verdade que o motor de detecção usa para montar
-- dinamicamente a query sobre system.access.audit. Table-driven = tunável
-- sem alterar código.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS capabilities (
    code              TEXT PRIMARY KEY,                       -- 'dashboard', 'genie', ...
    label             TEXT NOT NULL,                          -- rótulo p/ UI
    description       TEXT,
    audit_service     TEXT NOT NULL,                          -- system.access.audit.service_name
    audit_actions     TEXT[] NOT NULL,                        -- action_name(s) que contam como "criação"
    default_severity  TEXT NOT NULL DEFAULT 'warning',        -- info | warning | critical
    enabled           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_cap_severity CHECK (default_severity IN ('info','warning','critical'))
);

-- ---------------------------------------------------------------------
-- grants: quem pode criar o quê. principal = e-mail do usuário OU nome do
-- grupo. allowed=FALSE registra uma negação explícita.
-- workspace_id = '*' vale para a account inteira; um id específico vale só
-- naquele workspace. Precedência: escopo de workspace > '*'; dentro do mesmo
-- escopo, negação > concessão.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS grants (
    id              BIGSERIAL PRIMARY KEY,
    principal       TEXT NOT NULL,                            -- email (user) ou nome do grupo
    principal_type  TEXT NOT NULL DEFAULT 'user',             -- user | group
    capability      TEXT NOT NULL REFERENCES capabilities(code) ON DELETE CASCADE,
    workspace_id    TEXT NOT NULL DEFAULT '*',                -- '*' = todos os workspaces
    allowed         BOOLEAN NOT NULL DEFAULT TRUE,
    granted_by      TEXT,
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_grant_ptype CHECK (principal_type IN ('user','group')),
    CONSTRAINT uq_grant UNIQUE (principal, capability, workspace_id)
);
CREATE INDEX IF NOT EXISTS idx_grants_principal ON grants (lower(principal));

-- ---------------------------------------------------------------------
-- workspaces: nomes/URLs dos workspaces da account (para o filtro da UI).
-- Populada pelo job de detecção a partir de system.access.workspaces_latest.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id    TEXT PRIMARY KEY,
    workspace_name  TEXT,
    workspace_url   TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- alerts: violações detectadas (asset criado sem permissão). O ciclo de
-- vida é open -> investigating -> resolved | false_positive.
-- dedup_key evita alertas duplicados (idempotência do job de detecção).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id            BIGSERIAL PRIMARY KEY,
    principal     TEXT NOT NULL,
    capability    TEXT NOT NULL,
    asset_type    TEXT,                                       -- = capability.label (snapshot)
    asset_id      TEXT,
    asset_name    TEXT,
    service_name  TEXT,
    action_name   TEXT,
    workspace_id  TEXT,
    source_ip     TEXT,
    event_time    TIMESTAMPTZ,
    severity      TEXT NOT NULL DEFAULT 'warning',
    status        TEXT NOT NULL DEFAULT 'open',
    detected_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_by   TEXT,
    resolved_at   TIMESTAMPTZ,
    notes         TEXT,
    dedup_key     TEXT UNIQUE,                                -- ex.: request_id ou hash(event)
    raw_event     JSONB,
    CONSTRAINT chk_alert_severity CHECK (severity IN ('info','warning','critical')),
    CONSTRAINT chk_alert_status   CHECK (status IN ('open','investigating','resolved','false_positive'))
);
CREATE INDEX IF NOT EXISTS idx_alerts_status    ON alerts (status);
CREATE INDEX IF NOT EXISTS idx_alerts_principal ON alerts (lower(principal));
CREATE INDEX IF NOT EXISTS idx_alerts_event     ON alerts (event_time DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_ws        ON alerts (workspace_id, status);

-- ---------------------------------------------------------------------
-- alert_actions: trilha de remediação (notificado / revogado / deletado /
-- descartado). Toda ação sobre um alerta é registrada aqui.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alert_actions (
    id            BIGSERIAL PRIMARY KEY,
    alert_id      BIGINT NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    action        TEXT NOT NULL,                              -- notified | revoked | deleted | dismissed | status_change
    performed_by  TEXT,
    performed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    detail        TEXT
);
CREATE INDEX IF NOT EXISTS idx_alert_actions_alert ON alert_actions (alert_id);

-- ---------------------------------------------------------------------
-- detection_state: checkpoint incremental do job de detecção. Guarda o
-- maior event_time já processado para não reprocessar o audit inteiro.
-- Linha única (id=1).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS detection_state (
    id               INT PRIMARY KEY DEFAULT 1,
    last_event_time  TIMESTAMPTZ,
    last_run_at      TIMESTAMPTZ,
    last_run_status  TEXT,
    last_error       TEXT,
    CONSTRAINT chk_detection_singleton CHECK (id = 1)
);
INSERT INTO detection_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------
-- gateway_events: assets criados PELA app (caminho governado/OBO). Serve
-- como allowlist para o motor de detecção não gerar falso-positivo sobre
-- o que a própria app criou de forma autorizada.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gateway_events (
    id            BIGSERIAL PRIMARY KEY,
    principal     TEXT NOT NULL,
    capability    TEXT NOT NULL,
    asset_type    TEXT,
    asset_id      TEXT,
    asset_name    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    detail        JSONB
);
CREATE INDEX IF NOT EXISTS idx_gateway_principal ON gateway_events (lower(principal));

-- ---------------------------------------------------------------------
-- conversations / messages: histórico do chat do agente de criação,
-- por usuário (estilo Genie/Claude). Cada conversa tem N mensagens
-- (user/assistant); o assistant guarda o transcript das tools no JSONB.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversations (
    id          BIGSERIAL PRIMARY KEY,
    user_email  TEXT NOT NULL,
    title       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations (lower(user_email), updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,                 -- user | assistant
    content         TEXT,
    transcript      JSONB,                         -- passos/tools (turnos do assistant)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_msg_role CHECK (role IN ('user', 'assistant'))
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages (conversation_id, created_at);

-- =====================================================================
-- Seed das capacidades governáveis
-- (service_name / action_name descobertos em system.access.audit deste
--  workspace — 30–90 dias. Ajuste `enabled` / `default_severity` à vontade.)
-- =====================================================================
INSERT INTO capabilities (code, label, description, audit_service, audit_actions, default_severity) VALUES
    ('dashboard',     'Dashboard (AI/BI)',      'Criação de dashboards Lakeview/AI-BI',            'dashboards',                  ARRAY['createDashboard'],                  'warning'),
    ('genie',         'Genie Space',            'Criação de Genie spaces (text-to-SQL)',           'aibiGenie',                   ARRAY['genieCreateSpace','createSpace'],   'warning'),
    ('job',           'Job / Workflow',         'Criação de Jobs (Lakeflow)',                      'jobs',                        ARRAY['create'],                           'warning'),
    ('pipeline',      'Pipeline',               'Criação de pipelines (Lakeflow SDP)',             'pipelines',                   ARRAY['create'],                           'warning'),
    ('notebook',      'Notebook',               'Criação de notebooks',                            'notebook',                    ARRAY['createNotebook'],                   'info'),
    ('warehouse',     'SQL Warehouse',          'Criação de SQL warehouses',                       'databrickssql',               ARRAY['createWarehouse'],                  'critical'),
    ('query',         'SQL Query',              'Criação de queries no SQL editor',                'databrickssql',               ARRAY['createQuery'],                      'info'),
    ('sql_alert',     'SQL Alert',              'Criação de alertas de SQL',                       'databrickssql',               ARRAY['createAlert'],                      'info'),
    ('model_serving', 'Model Serving',          'Criação de endpoints de serving',                 'serverlessRealTimeInference', ARRAY['createServingEndpoint'],            'critical'),
    ('cluster',       'Cluster',                'Criação de clusters (compute all-purpose)',       'clusters',                    ARRAY['create'],                           'warning'),
    ('monitor',       'Lakehouse Monitor',      'Criação de monitores de qualidade de dados',      'dataMonitoring',              ARRAY['CreateMonitor'],                    'info'),
    ('registered_model','Registered Model (UC)','Registro de modelos no Unity Catalog',            'unityCatalog',                ARRAY['createRegisteredModel'],            'warning'),
    ('app',            'Databricks App',         'Criação de Databricks Apps',                      'apps',                        ARRAY['createApp'],                        'warning'),
    ('lakebase',       'Lakebase (DB Instance)', 'Criação de instâncias Lakebase (Postgres)',       'databaseInstances',           ARRAY['createDatabaseInstance'],           'warning'),
    ('ai_gateway',     'AI Gateway',             'Configuração de AI Gateway em serving endpoints',  'serverlessRealTimeInference', ARRAY['putInferenceEndpointAiGateway'],    'warning'),
    ('external_location','External Location (UC)','Criação de external locations (acesso a storage)', 'unityCatalog',               ARRAY['createExternalLocation'],           'critical'),
    ('storage_credential','Storage Credential (UC)','Criação de storage credentials',                'unityCatalog',                ARRAY['createStorageCredential'],          'critical'),
    ('connection',     'Connection (Federation)','Criação de conexões (Lakehouse Federation)',       'unityCatalog',                ARRAY['createConnection'],                 'warning'),
    ('delta_share',    'Delta Share',            'Criação de shares (compartilhamento externo)',     'unityCatalog',                ARRAY['createShare'],                      'critical'),
    ('recipient',      'Delta Recipient',        'Criação de recipients de Delta Sharing',           'unityCatalog',                ARRAY['createRecipient'],                  'critical'),
    ('vector_search',  'Vector Search Endpoint', 'Criação de endpoints de Vector Search',            'vectorSearch',                ARRAY['createEndpoint'],                   'warning'),
    ('vector_index',   'Vector Search Index',    'Criação de índices de Vector Search',              'vectorSearch',                ARRAY['createVectorIndex'],                'warning')
ON CONFLICT (code) DO NOTHING;

-- Por default deixamos habilitadas só as capacidades de ALTO SINAL. As
-- ruidosas (cluster = milhões de clusters automáticos; monitor/query/notebook/
-- sql_alert/registered_model = alto volume/baixo sinal) vêm desligadas.
-- Habilite qualquer uma pela UI quando quiser governá-la.
UPDATE capabilities SET enabled = FALSE
WHERE code IN ('cluster', 'monitor', 'query', 'notebook', 'sql_alert', 'registered_model');
