-- =====================================================================
-- Lakeguard — Unity Catalog objects (fc_catalog.lakeguard)
-- =====================================================================
-- Camada ANALÍTICA. A view abaixo enriquece system.access.audit expondo
-- SOMENTE os eventos de criação das capacidades governadas. Ela é usada:
--   1) pelo Genie space (text-to-SQL sobre "quem criou o quê")
--   2) pelo dashboard AI/BI de monitoramento
--   3) como referência p/ tunar o motor de detecção (jobs/detection)
--
-- O motor de detecção NÃO depende desta view (ele monta a query a partir
-- da tabela capabilities no Lakebase) — mas o mapeamento deve espelhá-la.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS fc_catalog.lakeguard
  COMMENT 'Lakeguard — governança/monitoramento de criação de assets';

-- ---------------------------------------------------------------------
-- v_creation_events: eventos de criação de assets governáveis, normalizados
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW fc_catalog.lakeguard.v_creation_events AS
SELECT
    event_time,
    event_date,
    user_identity.email                         AS principal,
    service_name,
    action_name,
    CASE
        WHEN service_name='dashboards'                  AND action_name='createDashboard'                    THEN 'dashboard'
        WHEN service_name='aibiGenie'                   AND action_name IN ('genieCreateSpace','createSpace') THEN 'genie'
        WHEN service_name='jobs'                        AND action_name='create'                              THEN 'job'
        WHEN service_name='pipelines'                   AND action_name='create'                              THEN 'pipeline'
        WHEN service_name='notebook'                    AND action_name='createNotebook'                      THEN 'notebook'
        WHEN service_name='databrickssql'               AND action_name='createWarehouse'                     THEN 'warehouse'
        WHEN service_name='databrickssql'               AND action_name='createQuery'                         THEN 'query'
        WHEN service_name='databrickssql'               AND action_name='createAlert'                         THEN 'sql_alert'
        WHEN service_name='serverlessRealTimeInference' AND action_name='createServingEndpoint'              THEN 'model_serving'
        WHEN service_name='serverlessRealTimeInference' AND action_name='putInferenceEndpointAiGateway'      THEN 'ai_gateway'
        WHEN service_name='clusters'                    AND action_name='create'                              THEN 'cluster'
        WHEN service_name='dataMonitoring'              AND action_name='CreateMonitor'                       THEN 'monitor'
        WHEN service_name='apps'                        AND action_name='createApp'                           THEN 'app'
        WHEN service_name='databaseInstances'           AND action_name='createDatabaseInstance'              THEN 'lakebase'
        WHEN service_name='unityCatalog'                AND action_name='createRegisteredModel'               THEN 'registered_model'
        WHEN service_name='unityCatalog'                AND action_name='createExternalLocation'              THEN 'external_location'
        WHEN service_name='unityCatalog'                AND action_name='createStorageCredential'             THEN 'storage_credential'
        WHEN service_name='unityCatalog'                AND action_name='createConnection'                    THEN 'connection'
        WHEN service_name='unityCatalog'                AND action_name='createShare'                         THEN 'delta_share'
        WHEN service_name='unityCatalog'                AND action_name='createRecipient'                     THEN 'recipient'
        WHEN service_name='vectorSearch'                AND action_name='createEndpoint'                      THEN 'vector_search'
        WHEN service_name='vectorSearch'                AND action_name='createVectorIndex'                   THEN 'vector_index'
    END                                          AS capability,
    workspace_id,
    source_ip_address                            AS source_ip,
    request_id,
    request_params,
    response.result                              AS response_result,
    response.status_code                         AS status_code,
    identity_metadata.run_by                     AS run_by,
    identity_metadata.run_as                     AS run_as
FROM system.access.audit
WHERE
    -- Escopo: a ACCOUNT inteira (system.access.audit é account-wide). O filtro
    -- por workspace é feito na app (alerts.workspace_id).
    (
        (service_name='dashboards'                  AND action_name='createDashboard')                    OR
        (service_name='aibiGenie'                   AND action_name IN ('genieCreateSpace','createSpace')) OR
        (service_name='jobs'                        AND action_name='create')                              OR
        (service_name='pipelines'                   AND action_name='create')                              OR
        (service_name='notebook'                    AND action_name='createNotebook')                      OR
        (service_name='databrickssql'               AND action_name IN ('createWarehouse','createQuery','createAlert')) OR
        (service_name='serverlessRealTimeInference' AND action_name IN ('createServingEndpoint','putInferenceEndpointAiGateway')) OR
        (service_name='clusters'                    AND action_name='create')                              OR
        (service_name='dataMonitoring'              AND action_name='CreateMonitor')                       OR
        (service_name='apps'                        AND action_name='createApp')                           OR
        (service_name='databaseInstances'           AND action_name='createDatabaseInstance')              OR
        (service_name='unityCatalog'                AND action_name IN ('createRegisteredModel','createExternalLocation','createStorageCredential','createConnection','createShare','createRecipient')) OR
        (service_name='vectorSearch'                AND action_name IN ('createEndpoint','createVectorIndex'))
    );
