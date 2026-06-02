-- Migration 013: Connector Dataset Metrics & Observations
-- Structured metric extraction from synced connector dataset rows.
-- Enables official-data metrics to appear alongside report-derived variables.

BEGIN;

-- ============================================================
-- connector_dataset_metrics: extracted metric definitions from synced datasets
-- ============================================================
CREATE TABLE IF NOT EXISTS connector_dataset_metrics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  dataset_id UUID NOT NULL REFERENCES connector_datasets(id) ON DELETE CASCADE,
  snapshot_id UUID NOT NULL REFERENCES connector_snapshots(id) ON DELETE CASCADE,
  metric_name TEXT NOT NULL,
  metric_description TEXT,
  unit TEXT,
  geography TEXT,
  time_period TEXT,
  category TEXT,
  dimension TEXT,
  source_url TEXT,
  retrieved_at TIMESTAMPTZ,
  confidence_score NUMERIC DEFAULT 0.8,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'needs_review', 'deprecated', 'superseded')),
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cdm_dataset ON connector_dataset_metrics(dataset_id);
CREATE INDEX IF NOT EXISTS idx_cdm_snapshot ON connector_dataset_metrics(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_cdm_metric_name ON connector_dataset_metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_cdm_geography ON connector_dataset_metrics(geography);
CREATE INDEX IF NOT EXISTS idx_cdm_status ON connector_dataset_metrics(status);
CREATE INDEX IF NOT EXISTS idx_cdm_category ON connector_dataset_metrics(category);

-- ============================================================
-- connector_dataset_observations: individual data points from synced rows
-- ============================================================
CREATE TABLE IF NOT EXISTS connector_dataset_observations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  metric_id UUID NOT NULL REFERENCES connector_dataset_metrics(id) ON DELETE CASCADE,
  dataset_id UUID NOT NULL REFERENCES connector_datasets(id) ON DELETE CASCADE,
  snapshot_id UUID NOT NULL REFERENCES connector_snapshots(id) ON DELETE CASCADE,
  value TEXT,
  value_numeric NUMERIC,
  time_period TEXT,
  geography TEXT,
  unit TEXT,
  dimension TEXT,
  dimension_value TEXT,
  row_json JSONB,
  confidence_score NUMERIC DEFAULT 0.8,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'needs_review', 'deprecated', 'superseded')),
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cdo_metric ON connector_dataset_observations(metric_id);
CREATE INDEX IF NOT EXISTS idx_cdo_dataset ON connector_dataset_observations(dataset_id);
CREATE INDEX IF NOT EXISTS idx_cdo_snapshot ON connector_dataset_observations(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_cdo_time ON connector_dataset_observations(time_period);
CREATE INDEX IF NOT EXISTS idx_cdo_geography ON connector_dataset_observations(geography);

-- ============================================================
-- Extend search_index object_type for connector metrics
-- ============================================================
ALTER TABLE search_index DROP CONSTRAINT IF EXISTS search_index_object_type_check;
ALTER TABLE search_index
  ADD CONSTRAINT search_index_object_type_check
  CHECK (object_type IN (
    'source', 'report', 'variable', 'dataset', 'chunk',
    'concept', 'organization', 'connector_dataset', 'connector_candidate',
    'connector_metric'
  ));

COMMIT;
