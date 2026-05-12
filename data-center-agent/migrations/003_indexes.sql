CREATE INDEX IF NOT EXISTS idx_sources_original_url ON sources(original_url);
CREATE INDEX IF NOT EXISTS idx_sources_source_type ON sources(source_type);
CREATE INDEX IF NOT EXISTS idx_reports_source_id ON reports(source_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_report_id ON document_chunks(report_id);
CREATE INDEX IF NOT EXISTS idx_report_variables_report_id ON report_variables(report_id);
CREATE INDEX IF NOT EXISTS idx_report_variables_raw_variable_name ON report_variables(raw_variable_name);
CREATE INDEX IF NOT EXISTS idx_variables_canonical_name ON variables(canonical_name);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_status ON ingestion_jobs(status);

CREATE INDEX IF NOT EXISTS idx_document_chunks_text_search
  ON document_chunks USING gin(to_tsvector('simple', chunk_text));

CREATE INDEX IF NOT EXISTS idx_report_variables_definition_search
  ON report_variables USING gin(to_tsvector('simple', coalesce(raw_variable_name, '') || ' ' || coalesce(definition, '')));
