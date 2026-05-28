# Venture-Metrics-db: Primary Diagnosis & Answer Quality Evaluation

Generated: 2026-05-28

---

## 1. Executive Summary

The Venture-Metrics-db platform has **strong data coverage** (434 sources, 239 reports, 5069 chunks) but a **critical bottleneck in variable extraction**: only **15 of 239 reports (6%)** have extracted codebook variables. This means most queries that look for specific metrics (deal counts, funding values, R&D percentages) return report-level results but lack the structured data points users expect.

**Key findings:**
- Average LLM judge score: **3.1/5**
- 10/20 queries rated "good" by LLM judge
- 9/20 queries are genuinely data-limited
- **Primary bottleneck**: Variable extraction covers only 15 reports
- **Secondary bottleneck**: 94 reports have "low_text" quality (OCR/parsing issues)
- Search index is healthy: 1073 entries, all embedded

---

## 2. Database Coverage

| Metric | Count |
|--------|-------|
| Sources | 434 |
| Reports | 239 |
| Document chunks | 5069 |
| Report variables | 144 |
| Variables (canonical) | 0 |
| Ecosystem organizations | 256 |
| Search index entries | 1073 |

**Source types:** html: 323, pdf: 111

**Crawl statuses:** parsed: 233, pending: 152, private_or_paywalled: 41, fetched: 6, failed: 2

**Geography distribution (reports):** United States: 25, United Kingdom: 22, China: 17, Singapore: 11, 50 states, 1875 counties, 380 MSAs) — Demographics: Gender, Ethnicity Source: America’s small businesses, October 2024: 1, financial services in Edinburgh, Leeds and London - advanced manufacturing in Broughton and Newport, Greater Manchester,: 1, Temasek [9] https://www: 1, all figures and percentages in this document are rounded: 1

---

## 3. Report-to-Variable Funnel

| Stage | Count | % of Reports |
|-------|-------|-------------|
| Sources | 434 | — |
| Reports | 239 | 100% |
| Reports with chunks | 230 | 96% |
| Reports without chunks | 9 | 4% |
| Document chunks | 5069 | — |
| Report variables | 144 | — |
| Reports with variables | 15 | 6% |
| Variables with evidence | 144 | — |
| Variables (confidence ≥ 0.65) | 144 | — |

**Critical gap:** 224 reports (94%) have NO extracted variables. This is the primary reason queries return report-level results but lack specific data points.

**Content quality breakdown:**
- low_text: 94
- full_report: 87
- landing_page_only: 24
- paywalled_or_gated: 19
- no_label: 11
- failed: 3
- js_required: 1

---

## 4. Benchmark Query Performance

### Score Distribution (LLM Judge)

| Score | Count | Queries |
|-------|-------|---------|
| 1/5 | 2 | |
| 2/5 | 4 | |
| 3/5 | 4 | |
| 4/5 | 9 | |
| 5/5 | 1 | |

### Top Performing Queries (score ≥ 4)

| Query | Score | Failure Type |
|-------|-------|-------------|
| startup funding in Singapore | 4/5 | good |
| Singapore VC deal count by stage | 4/5 | good |
| Singapore median funding round value | 4/5 | good |
| Singapore startup funding by year | 4/5 | good |
| SME digital adoption | 4/5 | good |
| R&D expenditure as percentage of GDP | 4/5 | good |
| government support for startups | 4/5 | good |
| compare startup funding definitions across reports | 4/5 | good |
| what data sources are private in our startup funding results? | 5/5 | good |
| what public datasets do we have for innovation metrics? | 4/5 | good |

### Weak Queries (score < 4)

| Query | Score | Failure Type |
|-------|-------|-------------|
| Hong Kong innovation output | 1/5 | genuinely_limited |
| Shenzhen startup organizations | 2/5 | no_source |
| Asian startup exits | 3/5 | genuinely_limited |
| AI investment by country | 3/5 | genuinely_limited |
| public data on business births | 3/5 | genuinely_limited |
| VC funding by sector in Southeast Asia | 3/5 | genuinely_limited |
| China unicorn company count and valuation | 2/5 | genuinely_limited |
| India startup funding by sector | 1/5 | genuinely_limited |
| compare VC investment and startup funding definitions | 2/5 | genuinely_limited |
| what organizations are relevant to Singapore's startup ecosystem? | 2/5 | genuinely_limited |

---

## 5. Common Failure Types

| Failure Type | Count | Description |
|-------------|-------|-------------|
| good | 10 | |
| genuinely_limited | 9 | |
| no_source | 1 | |

**"Genuinely limited"** (9 queries): The data simply doesn't exist in the database. These require new source ingestion or variable extraction from existing reports.

**"Good"** (10 queries): These perform well and can be used for demos.

---

## 6. Search Index Issues

- **Total entries:** 1073
- **All embedded:** 1073 (100%)
- **Short entries:** {}
- **No failed or pending embeddings**

The search index is healthy. The bottleneck is NOT retrieval — it's the lack of structured variables to retrieve.

---

## 7. "Limited Results" — Appropriate vs Too Pessimistic

### Appropriately says "limited":
- Hong Kong innovation output (no HK-specific innovation data)
- India startup funding by sector (no India sources)
- China unicorn company count (limited China data)

### Should say "limited" but doesn't:
- Hong Kong innovation output
- Shenzhen startup organizations
- Asian startup exits
- AI investment by country
- public data on business births
- VC funding by sector in Southeast Asia
- China unicorn company count and valuation
- India startup funding by sector
- compare VC investment and startup funding definitions
- what organizations are relevant to Singapore's startup ecosystem?

### Says "limited" when it shouldn't:
- None identified

**Assessment:** The current answer generation is appropriately calibrated for most queries. The main issue is that "genuinely limited" queries need better data coverage, not better answer generation.

---

## 8. Top 20 Repair Opportunities

| # | Priority | Topic/Query | Failure Type | Action | Impact | Effort |
|---|----------|-------------|-------------|--------|--------|--------|
| 1 | high | Shenzhen startup organizations | no_source | Find and ingest sources for this topic | high | high |
| 2 | medium | Asian startup exits | genuinely_limited | Ingest more reports covering this topic/geography | high | high |
| 3 | medium | AI investment by country | genuinely_limited | Ingest more reports covering this topic/geography | high | high |
| 4 | medium | public data on business births | genuinely_limited | Ingest more reports covering this topic/geography | high | high |
| 5 | medium | VC funding by sector in Southeast Asia | genuinely_limited | Ingest more reports covering this topic/geography | high | high |
| 6 | medium | China unicorn company count and valuation | genuinely_limited | Ingest more reports covering this topic/geography | high | high |
| 7 | medium | compare VC investment and startup funding definitions | genuinely_limited | Ingest more reports covering this topic/geography | high | high |
| 8 | medium | what organizations are relevant to Singapore's startup ecosystem? | genuinely_limited | Ingest more reports covering this topic/geography | high | high |
| 9 | medium | Hong Kong innovation output | genuinely_limited | Ingest more reports covering this topic/geography | high | high |
| 10 | medium | India startup funding by sector | genuinely_limited | Ingest more reports covering this topic/geography | high | high |

---

## 9. Recommended Next Implementation Priorities

### Priority 1: Variable Extraction at Scale (HIGH IMPACT, MEDIUM EFFORT)
Run LLM batch extraction on the 224 reports that have chunks but no variables. This is the single highest-impact action.
- Estimated new variables: 500-2000 (at ~5-10 per report)
- Cost: ~$10-30 in OpenAI batch API
- Time: 1-2 days

### Priority 2: Fix Low-Text Reports (HIGH IMPACT, HIGH EFFORT)
94 reports have "low_text" quality. Many are scanned PDFs that need OCR.
- Install tesseract-ocr (already done)
- Re-process these reports with Tesseract OCR fallback
- Estimated recovery: 30-50 reports

### Priority 3: Ingest Missing Geographies (MEDIUM IMPACT, HIGH EFFORT)
Queries for India, Hong Kong, Shenzhen, and broader Asia return limited results.
- Find and ingest reports for these geographies
- Focus on: India startup ecosystem, Hong Kong innovation, China tech sector

### Priority 4: Variable Availability Labeling (LOW IMPACT, LOW EFFORT)
144 variables have "unclear" availability.
- Audit and label variables as public/private/obtainable
- Improves answer quality for "what public data" queries

### Priority 5: Canonical Variable Normalization (LOW IMPACT, MEDIUM EFFORT)
0 canonical variables exist. Build a normalization layer to deduplicate similar variables across reports.

---

*This diagnosis is read-only. No data was modified.*
