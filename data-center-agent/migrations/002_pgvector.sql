CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE document_chunks
  ADD COLUMN IF NOT EXISTS embedding vector;

ALTER TABLE variables
  ADD COLUMN IF NOT EXISTS embedding vector;

-- Vector dimensions are intentionally not fixed in the MVP.
-- When the embedding model is selected, change these columns to vector(N)
-- and add ivfflat or hnsw indexes with the appropriate operator class.
