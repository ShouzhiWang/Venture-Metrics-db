ALTER TABLE sources
  ADD COLUMN IF NOT EXISTS parent_source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS source_role TEXT,
  ADD COLUMN IF NOT EXISTS resolution_status TEXT,
  ADD COLUMN IF NOT EXISTS resolved_source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS resolution_notes TEXT,
  ADD COLUMN IF NOT EXISTS discovered_artifacts JSONB;

CREATE INDEX IF NOT EXISTS idx_sources_parent_source_id ON sources(parent_source_id);
CREATE INDEX IF NOT EXISTS idx_sources_resolved_source_id ON sources(resolved_source_id);
CREATE INDEX IF NOT EXISTS idx_sources_source_role ON sources(source_role);
CREATE INDEX IF NOT EXISTS idx_sources_resolution_status ON sources(resolution_status);
