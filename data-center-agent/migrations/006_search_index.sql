CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS search_index (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  object_type TEXT NOT NULL CHECK (object_type IN ('source', 'report', 'variable', 'dataset', 'chunk', 'concept')),
  object_id UUID NOT NULL,
  title TEXT,
  content TEXT NOT NULL,
  search_text TEXT NOT NULL,
  source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
  report_id UUID REFERENCES reports(id) ON DELETE SET NULL,
  variable_id UUID REFERENCES report_variables(id) ON DELETE SET NULL,
  dataset_id UUID REFERENCES datasets(id) ON DELETE SET NULL,
  chunk_id UUID REFERENCES document_chunks(id) ON DELETE SET NULL,
  geography TEXT,
  time_coverage TEXT,
  availability TEXT NOT NULL DEFAULT 'unclear',
  source_url TEXT,
  local_path TEXT,
  evidence_quote TEXT,
  rank_weight NUMERIC NOT NULL DEFAULT 1.0,
  embedding vector(1024),
  embedding_provider TEXT,
  embedding_model TEXT,
  embedding_dimension INTEGER,
  embedding_normalized BOOLEAN NOT NULL DEFAULT true,
  embedding_status TEXT NOT NULL DEFAULT 'pending' CHECK (embedding_status IN ('pending', 'embedded', 'failed', 'skipped')),
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (object_type, object_id)
);

CREATE INDEX IF NOT EXISTS idx_search_index_object_type ON search_index(object_type);
CREATE INDEX IF NOT EXISTS idx_search_index_object_id ON search_index(object_id);
CREATE INDEX IF NOT EXISTS idx_search_index_report_id ON search_index(report_id);
CREATE INDEX IF NOT EXISTS idx_search_index_source_id ON search_index(source_id);
CREATE INDEX IF NOT EXISTS idx_search_index_variable_id ON search_index(variable_id);
CREATE INDEX IF NOT EXISTS idx_search_index_dataset_id ON search_index(dataset_id);
CREATE INDEX IF NOT EXISTS idx_search_index_chunk_id ON search_index(chunk_id);
CREATE INDEX IF NOT EXISTS idx_search_index_embedding_status ON search_index(embedding_status);
CREATE INDEX IF NOT EXISTS idx_search_index_search_text_trgm
  ON search_index USING gin (search_text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_search_index_embedding_cosine
  ON search_index USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100)
  WHERE embedding_status = 'embedded';
