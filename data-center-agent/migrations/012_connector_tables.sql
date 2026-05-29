-- Migration 012: Connector Architecture Tables
-- Targeted API/Data Connector system for discovering, classifying, syncing,
-- and caching external data sources.

BEGIN;

-- ============================================================
-- external_source_candidates: metadata-only discovery records
-- ============================================================
CREATE TABLE IF NOT EXISTS external_source_candidates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT,
  url TEXT,
  source_kind TEXT NOT NULL DEFAULT 'unknown',
  candidate_type TEXT,
  geography TEXT,
  ecosystem_category TEXT,
  discovery_method TEXT,
  confidence_score NUMERIC,
  status TEXT NOT NULL DEFAULT 'pending_review'
    CHECK (status IN (
      'pending_review', 'approved', 'synced', 'extracted',
      'rejected', 'failed', 'needs_connector'
    )),
  source_set TEXT,
  raw_row_metadata JSONB,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_esc_url_unique
  ON external_source_candidates(url) WHERE url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_esc_source_kind ON external_source_candidates(source_kind);
CREATE INDEX IF NOT EXISTS idx_esc_status ON external_source_candidates(status);
CREATE INDEX IF NOT EXISTS idx_esc_geography ON external_source_candidates(geography);
CREATE INDEX IF NOT EXISTS idx_esc_source_set ON external_source_candidates(source_set);

-- ============================================================
-- connector_datasets: discovered datasets (distinct from codebook datasets)
-- ============================================================
CREATE TABLE IF NOT EXISTS connector_datasets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  description TEXT,
  publisher TEXT,
  geography TEXT,
  topic TEXT,
  source_url TEXT,
  portal TEXT,
  license TEXT,
  update_frequency TEXT,
  last_modified_external TIMESTAMPTZ,
  access_type TEXT NOT NULL DEFAULT 'unknown'
    CHECK (access_type IN (
      'api', 'csv', 'xlsx', 'html_table', 'portal', 'manual', 'unknown'
    )),
  status TEXT NOT NULL DEFAULT 'discovered'
    CHECK (status IN (
      'discovered', 'approved', 'synced', 'failed', 'archived'
    )),
  source_candidate_id UUID REFERENCES external_source_candidates(id) ON DELETE SET NULL,
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cd_status ON connector_datasets(status);
CREATE INDEX IF NOT EXISTS idx_cd_geography ON connector_datasets(geography);
CREATE INDEX IF NOT EXISTS idx_cd_access_type ON connector_datasets(access_type);
CREATE INDEX IF NOT EXISTS idx_cd_source_candidate ON connector_datasets(source_candidate_id);

-- ============================================================
-- connector_resources: individual files/APIs within a dataset
-- ============================================================
CREATE TABLE IF NOT EXISTS connector_resources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  dataset_id UUID NOT NULL REFERENCES connector_datasets(id) ON DELETE CASCADE,
  resource_name TEXT,
  resource_url TEXT,
  format TEXT NOT NULL DEFAULT 'unknown'
    CHECK (format IN (
      'api', 'csv', 'xlsx', 'json', 'html', 'pdf', 'unknown'
    )),
  schema_metadata JSONB,
  local_path TEXT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN (
      'pending', 'downloaded', 'synced', 'failed', 'archived'
    )),
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cr_dataset ON connector_resources(dataset_id);
CREATE INDEX IF NOT EXISTS idx_cr_status ON connector_resources(status);
CREATE INDEX IF NOT EXISTS idx_cr_format ON connector_resources(format);

-- ============================================================
-- connector_snapshots: reproducible point-in-time data captures
-- ============================================================
CREATE TABLE IF NOT EXISTS connector_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  dataset_id UUID NOT NULL REFERENCES connector_datasets(id) ON DELETE CASCADE,
  resource_id UUID REFERENCES connector_resources(id) ON DELETE SET NULL,
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  query_params JSONB,
  row_count INTEGER,
  column_count INTEGER,
  local_path TEXT,
  checksum TEXT,
  schema_version TEXT,
  status TEXT NOT NULL DEFAULT 'captured'
    CHECK (status IN (
      'captured', 'validated', 'failed', 'archived'
    )),
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cs_dataset ON connector_snapshots(dataset_id);
CREATE INDEX IF NOT EXISTS idx_cs_resource ON connector_snapshots(resource_id);
CREATE INDEX IF NOT EXISTS idx_cs_retrieved ON connector_snapshots(retrieved_at);

-- ============================================================
-- connector_rows: flexible row-level storage (row_json first)
-- ============================================================
CREATE TABLE IF NOT EXISTS connector_rows (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  snapshot_id UUID NOT NULL REFERENCES connector_snapshots(id) ON DELETE CASCADE,
  row_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_crow_snapshot ON connector_rows(snapshot_id);

-- ============================================================
-- Extend search_index object_type to include connector objects
-- ============================================================
ALTER TABLE search_index DROP CONSTRAINT IF EXISTS search_index_object_type_check;
ALTER TABLE search_index
  ADD CONSTRAINT search_index_object_type_check
  CHECK (object_type IN (
    'source', 'report', 'variable', 'dataset', 'chunk',
    'concept', 'organization', 'connector_dataset', 'connector_candidate'
  ));

COMMIT;
