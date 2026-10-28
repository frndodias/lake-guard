-- =====================================================================
-- Migração 002 — Lakeguard account-wide
-- Aplica no banco `lakeguard` já existente (instalações novas usam
-- sql/lakebase_schema.sql, que já contém estas mudanças).
-- =====================================================================
SET search_path TO lakeguard;

-- escopo opcional por workspace nas concessões ('*' = account inteira)
ALTER TABLE grants ADD COLUMN IF NOT EXISTS workspace_id TEXT NOT NULL DEFAULT '*';
ALTER TABLE grants DROP CONSTRAINT IF EXISTS uq_grant;
ALTER TABLE grants ADD CONSTRAINT uq_grant UNIQUE (principal, capability, workspace_id);

-- nomes/URLs dos workspaces (populada pelo job de detecção)
CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id    TEXT PRIMARY KEY,
    workspace_name  TEXT,
    workspace_url   TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_alerts_ws ON alerts (workspace_id, status);
