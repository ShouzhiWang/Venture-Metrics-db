CREATE TABLE IF NOT EXISTS llm_extraction_batches (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  provider TEXT NOT NULL DEFAULT 'openai',
  batch_kind TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  openai_batch_id TEXT,
  input_file_id TEXT,
  output_file_id TEXT,
  error_file_id TEXT,
  status TEXT NOT NULL,
  report_ids JSONB,
  input_path TEXT,
  output_path TEXT,
  error_path TEXT,
  request_count INTEGER,
  estimated_input_tokens INTEGER,
  estimated_output_tokens INTEGER,
  estimated_cost NUMERIC,
  submitted_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  imported_at TIMESTAMPTZ,
  error_message TEXT,
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS llm_extraction_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_id UUID NOT NULL REFERENCES llm_extraction_batches(id) ON DELETE CASCADE,
  request_custom_id TEXT NOT NULL,
  report_id UUID,
  status TEXT NOT NULL DEFAULT 'pending',
  raw_response JSONB,
  parsed_items JSONB,
  validation_errors JSONB,
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_llm_extraction_batches_openai_batch_id ON llm_extraction_batches(openai_batch_id);
CREATE INDEX IF NOT EXISTS idx_llm_extraction_batches_status ON llm_extraction_batches(status);
CREATE INDEX IF NOT EXISTS idx_llm_extraction_batches_batch_kind ON llm_extraction_batches(batch_kind);
CREATE INDEX IF NOT EXISTS idx_llm_extraction_items_batch_id ON llm_extraction_items(batch_id);
CREATE INDEX IF NOT EXISTS idx_llm_extraction_items_report_id ON llm_extraction_items(report_id);
CREATE INDEX IF NOT EXISTS idx_llm_extraction_items_request_custom_id ON llm_extraction_items(request_custom_id);
