CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS sources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  original_url TEXT UNIQUE,
  source_type TEXT NOT NULL DEFAULT 'unknown',
  source_owner TEXT,
  access_type TEXT NOT NULL DEFAULT 'unknown',
  detected_format TEXT,
  title TEXT,
  crawl_status TEXT NOT NULL DEFAULT 'pending',
  raw_file_path TEXT,
  raw_file_sha256 TEXT,
  mime_type TEXT,
  last_checked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  notes TEXT
);

CREATE TABLE IF NOT EXISTS reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
  title TEXT,
  publisher TEXT,
  publication_date DATE,
  report_year INTEGER,
  geography TEXT,
  language TEXT,
  summary TEXT,
  raw_text_path TEXT,
  parsed_json_path TEXT,
  citation_info JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
  report_id UUID REFERENCES reports(id) ON DELETE SET NULL,
  input_payload JSONB,
  output_payload JSONB,
  error_message TEXT,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id UUID NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
  chunk_text TEXT NOT NULL,
  page_number INTEGER,
  section_title TEXT,
  chunk_type TEXT NOT NULL DEFAULT 'unknown',
  token_count INTEGER,
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS datasets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  report_id UUID REFERENCES reports(id) ON DELETE SET NULL,
  dataset_name TEXT,
  data_origin_type TEXT NOT NULL DEFAULT 'unknown',
  temporal_coverage_start DATE,
  temporal_coverage_end DATE,
  geography_coverage TEXT,
  license_or_access_note TEXT,
  raw_data_path TEXT,
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS variables (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_name TEXT,
  display_name TEXT,
  concept_group TEXT,
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS report_variables (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id UUID NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
  variable_id UUID REFERENCES variables(id) ON DELETE SET NULL,
  raw_variable_name TEXT NOT NULL,
  definition TEXT,
  measurement_method TEXT,
  unit TEXT,
  data_source_text TEXT,
  data_source_type TEXT NOT NULL DEFAULT 'unknown',
  availability TEXT NOT NULL DEFAULT 'unclear',
  temporal_coverage TEXT,
  geographic_coverage TEXT,
  page_number INTEGER,
  evidence_chunk_id UUID REFERENCES document_chunks(id) ON DELETE SET NULL,
  confidence_score NUMERIC,
  review_status TEXT NOT NULL DEFAULT 'pending',
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS variable_comparisons (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  variable_a_id UUID NOT NULL REFERENCES report_variables(id) ON DELETE CASCADE,
  variable_b_id UUID NOT NULL REFERENCES report_variables(id) ON DELETE CASCADE,
  similarity_score NUMERIC,
  same_name_different_definition BOOLEAN,
  same_concept_different_measurement BOOLEAN,
  difference_summary TEXT,
  generated_by_model TEXT,
  reviewed_by_human BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
