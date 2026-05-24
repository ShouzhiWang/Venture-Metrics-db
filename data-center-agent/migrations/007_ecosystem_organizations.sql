CREATE TABLE IF NOT EXISTS ecosystem_organizations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  website_url TEXT,
  description TEXT,
  organization_type TEXT,
  geography TEXT,
  country TEXT,
  city TEXT,
  region TEXT,
  sector_focus TEXT[],
  stage_focus TEXT[],
  market_focus TEXT[],
  source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
  original_source_url TEXT,
  confidence_score NUMERIC,
  review_status TEXT NOT NULL DEFAULT 'pending',
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ecosystem_organizations_source_id_unique
  ON ecosystem_organizations(source_id)
  WHERE source_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_ecosystem_organizations_website_url_unique
  ON ecosystem_organizations(website_url)
  WHERE website_url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ecosystem_organizations_name ON ecosystem_organizations(name);
CREATE INDEX IF NOT EXISTS idx_ecosystem_organizations_type ON ecosystem_organizations(organization_type);
CREATE INDEX IF NOT EXISTS idx_ecosystem_organizations_geography ON ecosystem_organizations(geography);
CREATE INDEX IF NOT EXISTS idx_ecosystem_organizations_source_id ON ecosystem_organizations(source_id);

ALTER TABLE search_index DROP CONSTRAINT IF EXISTS search_index_object_type_check;
ALTER TABLE search_index
  ADD CONSTRAINT search_index_object_type_check
  CHECK (object_type IN ('source', 'report', 'variable', 'dataset', 'chunk', 'concept', 'organization'));
