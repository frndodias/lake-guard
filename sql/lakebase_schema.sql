-- =====================================================================
-- Lakeguard v2 — Lakebase (PostgreSQL) operational schema  (schema: lg)
-- =====================================================================
-- Estado OPERACIONAL do app + espelho compacto do inventário 360 para a UI.
-- A cópia analítica do inventário fica em Delta (fc_catalog.lakeguard.inv_*).
--
-- Rode como o dono da instância (ver setup/provision.md). Idempotente.
-- O schema antigo `lakeguard` (v0.1) não é tocado.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS lg;
SET search_path TO lg;

-- ---------------------------------------------------------------------
-- Configuração
-- ---------------------------------------------------------------------
-- settings: chave/valor (prefixo de grupos, modo demo, auto-aprovação…)
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL,
    updated_by  TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- catalogs: nome LÓGICO do modelo (raw, data_products_prd…) → catalog físico.
-- managed = o app pode aplicar GRANTs nele.
CREATE TABLE IF NOT EXISTS catalogs (
    logical_name   TEXT PRIMARY KEY,
    physical_name  TEXT NOT NULL UNIQUE,
    layer          TEXT NOT NULL,          -- raw | product | dev | sandbox | billing | ds | system
    env            TEXT NOT NULL,          -- prd | dev | n/a
    description    TEXT,
    managed        BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order     INT NOT NULL DEFAULT 100
);

-- domains: schema de domínio em data_products_prd (camada product)
CREATE TABLE IF NOT EXISTS domains (
    code            TEXT PRIMARY KEY,               -- finance, marketing…
    name            TEXT NOT NULL,
    schema_name     TEXT NOT NULL UNIQUE,           -- data_finance…
    owner           TEXT,
    sensitivity     TEXT NOT NULL DEFAULT 'normal', -- normal | restricted | critical
    clearance_group TEXT,                           -- grupo clearance-* (sem prefixo de demo)
    description     TEXT,
    CONSTRAINT chk_domain_sens CHECK (sensitivity IN ('normal','restricted','critical'))
);

-- app_roles: controle de acesso do PRÓPRIO app
CREATE TABLE IF NOT EXISTS app_roles (
    id              BIGSERIAL PRIMARY KEY,
    principal       TEXT NOT NULL,                  -- e-mail ou nome de grupo
    principal_type  TEXT NOT NULL DEFAULT 'user',
    role            TEXT NOT NULL,                  -- admin | steward | dpo | auditor
    domain          TEXT REFERENCES domains(code) ON DELETE CASCADE,  -- só p/ steward
    granted_by      TEXT,
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_role CHECK (role IN ('admin','steward','dpo','auditor')),
    CONSTRAINT chk_role_ptype CHECK (principal_type IN ('user','group'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_app_roles
    ON app_roles (lower(principal), role, COALESCE(domain, ''));

-- ---------------------------------------------------------------------
-- Modelo de personas (estado DESEJADO)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS personas (
    code            TEXT PRIMARY KEY,               -- sql-explorer…
    label           TEXT NOT NULL,
    category        TEXT NOT NULL,                  -- Consumer | Explorer | Creator | Conductor | Platform
    description     TEXT,
    group_name      TEXT NOT NULL UNIQUE,           -- persona-sql-explorer (sem prefixo de demo)
    idp_group_name  TEXT,                           -- idp-persona-sql-explorer
    version         INT NOT NULL DEFAULT 1,
    sort_order      INT NOT NULL DEFAULT 100,
    updated_by      TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- persona_grants: privilégios desejados por catalog lógico.
-- schema_scope: NULL = catalog inteiro | '@staging' | '@product' | nome de schema
CREATE TABLE IF NOT EXISTS persona_grants (
    id              BIGSERIAL PRIMARY KEY,
    persona_code    TEXT NOT NULL REFERENCES personas(code) ON DELETE CASCADE,
    catalog_logical TEXT NOT NULL REFERENCES catalogs(logical_name) ON DELETE CASCADE,
    schema_scope    TEXT,
    privileges      TEXT[] NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_persona_grants
    ON persona_grants (persona_code, catalog_logical, COALESCE(schema_scope, ''));

-- capabilities: o que pode ser CRIADO (mapeado ao audit log) — herdado do v0.1
CREATE TABLE IF NOT EXISTS capabilities (
    code             TEXT PRIMARY KEY,
    label            TEXT NOT NULL,
    audit_service    TEXT NOT NULL,
    audit_actions    TEXT[] NOT NULL,
    severity         TEXT NOT NULL DEFAULT 'warning'
);

CREATE TABLE IF NOT EXISTS persona_capabilities (
    persona_code  TEXT NOT NULL REFERENCES personas(code) ON DELETE CASCADE,
    capability    TEXT NOT NULL REFERENCES capabilities(code) ON DELETE CASCADE,
    PRIMARY KEY (persona_code, capability)
);

-- persona_versions: snapshot completo a cada mudança aplicada (rollback)
CREATE TABLE IF NOT EXISTS persona_versions (
    id            BIGSERIAL PRIMARY KEY,
    persona_code  TEXT NOT NULL REFERENCES personas(code) ON DELETE CASCADE,
    version       INT NOT NULL,
    snapshot      JSONB NOT NULL,
    change_id     BIGINT,
    changed_by    TEXT,
    changed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (persona_code, version)
);

-- ---------------------------------------------------------------------
-- Mudanças, pedidos e aprovações
-- ---------------------------------------------------------------------
-- change_requests: toda mudança passa por aqui (proposta → aprovação → aplicação)
--   kind: persona_update | gap_fix | membership_add | membership_remove |
--         access_request | migration_wave | migration_rollback | alert_fix
CREATE TABLE IF NOT EXISTS change_requests (
    id               BIGSERIAL PRIMARY KEY,
    kind             TEXT NOT NULL,
    title            TEXT NOT NULL,
    target           TEXT,                          -- persona/grupo/onda afetado
    domain           TEXT,                          -- p/ roteamento ao steward
    payload          JSONB NOT NULL DEFAULT '{}',
    plan             JSONB NOT NULL DEFAULT '[]',   -- lista de operações
    impact           JSONB,
    justification    TEXT,
    duration_days    INT,
    requires_dpo     BOOLEAN NOT NULL DEFAULT FALSE,
    status           TEXT NOT NULL DEFAULT 'pending',
    requested_by     TEXT NOT NULL,
    approved_by      TEXT,
    approved_at      TIMESTAMPTZ,
    dpo_approved_by  TEXT,
    dpo_approved_at  TIMESTAMPTZ,
    rejected_by      TEXT,
    decision_note    TEXT,
    applied_at       TIMESTAMPTZ,
    expires_at       TIMESTAMPTZ,
    result           JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_cr_status CHECK (status IN
        ('pending','approved','rejected','applied','failed','expired','revoked','cancelled'))
);
CREATE INDEX IF NOT EXISTS idx_cr_status ON change_requests (status, created_at DESC);

-- manual_members: membros adicionados pelo app (fora do IdP), com prazo
CREATE TABLE IF NOT EXISTS manual_members (
    id            BIGSERIAL PRIMARY KEY,
    group_name    TEXT NOT NULL,                    -- nome físico do grupo
    member_id     TEXT NOT NULL,                    -- id SCIM
    member_name   TEXT NOT NULL,
    member_type   TEXT NOT NULL,                    -- user | sp | group
    justification TEXT,
    approved_by   TEXT,
    change_id     BIGINT REFERENCES change_requests(id),
    expires_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    removed_at    TIMESTAMPTZ,
    removed_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_mm_active ON manual_members (group_name) WHERE removed_at IS NULL;

-- ---------------------------------------------------------------------
-- Migração (tombamento)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS migration_mappings (
    legacy_group  TEXT PRIMARY KEY,                 -- nome físico do grupo legado
    action        TEXT NOT NULL,                    -- to_persona | to_clearance | delete | to_sp | shrink_to_floor | keep
    target        TEXT,                             -- persona code / domain code
    suggested     BOOLEAN NOT NULL DEFAULT TRUE,    -- ainda é sugestão automática?
    rationale     TEXT,
    status        TEXT NOT NULL DEFAULT 'planned',  -- planned | migrated | rolled_back
    updated_by    TEXT,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS migration_waves (
    id            BIGSERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    wave_order    INT NOT NULL DEFAULT 1,
    groups        TEXT[] NOT NULL,
    status        TEXT NOT NULL DEFAULT 'draft',    -- draft | pending | executed | rolled_back
    snapshot      JSONB,                            -- membros removidos (p/ rollback)
    change_id     BIGINT,
    created_by    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    executed_at   TIMESTAMPTZ
);

-- ---------------------------------------------------------------------
-- Regras e alertas
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id            BIGSERIAL PRIMARY KEY,
    rule          TEXT NOT NULL,
    severity      TEXT NOT NULL DEFAULT 'warning',  -- info | warning | critical
    title         TEXT NOT NULL,
    principal     TEXT,
    object        TEXT,
    detail        JSONB,
    fixable       BOOLEAN NOT NULL DEFAULT FALSE,
    status        TEXT NOT NULL DEFAULT 'open',     -- open | acknowledged | resolved
    dedup_key     TEXT NOT NULL UNIQUE,
    first_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_by   TEXT,
    resolved_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts (status, severity);

-- action_log: trilha de auditoria do app
CREATE TABLE IF NOT EXISTS action_log (
    id      BIGSERIAL PRIMARY KEY,
    actor   TEXT NOT NULL,
    action  TEXT NOT NULL,
    target  TEXT,
    detail  JSONB,
    at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_log_at ON action_log (at DESC);

-- ---------------------------------------------------------------------
-- Inventário 360 (espelho para a UI — reescrito pelo job a cada execução)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inv_state (
    id            INT PRIMARY KEY DEFAULT 1,
    last_run_at   TIMESTAMPTZ,
    status        TEXT,
    error         TEXT,
    counts        JSONB,
    CONSTRAINT chk_inv_singleton CHECK (id = 1)
);
INSERT INTO inv_state (id) VALUES (1) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS inv_principals (
    id            TEXT PRIMARY KEY,                 -- id SCIM
    type          TEXT NOT NULL,                    -- user | group | sp
    name          TEXT NOT NULL,                    -- e-mail (user), displayName (group), applicationId (sp)
    display_name  TEXT,
    active        BOOLEAN,
    group_class   TEXT,                             -- p/ grupos: persona | idp_persona | clearance | legacy | clone | system | other
    persona_code  TEXT,                             -- p/ grupos persona/idp_persona
    in_scope      BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_invp_name ON inv_principals (lower(name));

-- membros DIRETOS
CREATE TABLE IF NOT EXISTS inv_memberships (
    group_id     TEXT NOT NULL,
    member_id    TEXT NOT NULL,
    PRIMARY KEY (group_id, member_id)
);

-- fechamento transitivo: member pertence a group (depth 1 = direto), path = nomes
CREATE TABLE IF NOT EXISTS inv_closure (
    member_id   TEXT NOT NULL,
    group_id    TEXT NOT NULL,
    depth       INT NOT NULL,
    path        TEXT[] NOT NULL,
    PRIMARY KEY (member_id, group_id)
);
CREATE INDEX IF NOT EXISTS idx_closure_group ON inv_closure (group_id);

CREATE TABLE IF NOT EXISTS inv_securables (
    full_name        TEXT PRIMARY KEY,              -- cat | cat.sch | cat.sch.tbl
    type             TEXT NOT NULL,                 -- catalog | schema | table | view
    catalog          TEXT NOT NULL,
    schema_name      TEXT,
    table_name       TEXT,
    catalog_logical  TEXT,
    domain           TEXT,
    owner            TEXT,
    created_by       TEXT,
    created_at       TIMESTAMPTZ,
    sensitivity      TEXT,                          -- valor da tag de sensibilidade
    tags             JSONB
);
CREATE INDEX IF NOT EXISTS idx_sec_catalog ON inv_securables (catalog, schema_name);

-- GRANTs DIRETOS (um por privilégio)
CREATE TABLE IF NOT EXISTS inv_grants (
    securable    TEXT NOT NULL,
    sec_type     TEXT NOT NULL,
    principal    TEXT NOT NULL,                     -- nome como o UC reporta
    principal_id TEXT,                              -- id SCIM resolvido (quando possível)
    privilege    TEXT NOT NULL,
    PRIMARY KEY (securable, principal, privilege)
);
CREATE INDEX IF NOT EXISTS idx_grants_principal ON inv_grants (principal_id);

-- uso agregado por dia (real = system tables, demo = semente simulada)
CREATE TABLE IF NOT EXISTS inv_usage (
    day          DATE NOT NULL,
    principal_id TEXT NOT NULL,
    securable    TEXT NOT NULL,                     -- tabela
    action       TEXT NOT NULL,                     -- read | write | denied
    n            INT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'real',
    PRIMARY KEY (day, principal_id, securable, action, source)
);
CREATE INDEX IF NOT EXISTS idx_usage_principal ON inv_usage (principal_id);
CREATE INDEX IF NOT EXISTS idx_usage_sec ON inv_usage (securable);

-- assets criados (dashboards, jobs, genie…)
CREATE TABLE IF NOT EXISTS inv_creations (
    id           BIGSERIAL PRIMARY KEY,
    event_time   TIMESTAMPTZ NOT NULL,
    principal_id TEXT NOT NULL,
    capability   TEXT NOT NULL,
    workspace_id TEXT,
    asset_id     TEXT,
    asset_name   TEXT,
    location     TEXT,                              -- catalog/schema ou pasta
    source       TEXT NOT NULL DEFAULT 'real'
);
CREATE INDEX IF NOT EXISTS idx_creations_principal ON inv_creations (principal_id);

-- eventos de mudança de permissão (p/ regra de auto-atribuição)
CREATE TABLE IF NOT EXISTS inv_permission_events (
    id           BIGSERIAL PRIMARY KEY,
    event_time   TIMESTAMPTZ NOT NULL,
    actor        TEXT NOT NULL,
    securable    TEXT,
    grantee      TEXT,
    detail       JSONB,
    source       TEXT NOT NULL DEFAULT 'real'
);

-- workspaces (nome para exibição)
CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id   TEXT PRIMARY KEY,
    workspace_name TEXT,
    workspace_url  TEXT
);

-- ---------------------------------------------------------------------
-- Permissões para o service principal do app (role criado pelo binding)
-- Substitua :app_role pelo client_id do SP (ver setup/provision.md).
-- ---------------------------------------------------------------------
-- GRANT USAGE ON SCHEMA lg TO "<app_sp>";
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA lg TO "<app_sp>";
-- GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA lg TO "<app_sp>";
-- ALTER DEFAULT PRIVILEGES IN SCHEMA lg GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "<app_sp>";
-- ALTER DEFAULT PRIVILEGES IN SCHEMA lg GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO "<app_sp>";
