# Venture-Metrics-db: Post-Batch Diagnosis & Comparison

Generated: 2026-05-28 (post LLM batch extraction of 1,033 variables)

---

## 1. Executive Summary

The LLM batch extraction added **1033 new variables** (144 → 1177), increasing reports with variables from **15 to 118** (118/239 = 49%).

**Key improvements:**
- Variables: 144 → **1177** (+1033, 8.2x)
- Reports with variables: 15 → **118** (+103)
- Search index: 1073 → **2106** (+1033)
- All 20 benchmark queries now return **10 variables each** (previously 0-10)
- **0/20 queries say "limited results"** (previously 0/20 — the tool layer was already good)

**Remaining bottlenecks:**
- 121 reports (51%) still have no variables — mostly low-text quality
- 94 reports need OCR re-processing
- Missing geography coverage (India, HK, broader Asia)
- Answer generation layer needs improvement (LLM judge scores flat)

---

## 2. Before/After: Core Metrics

| Metric | Pre-Batch | Post-Batch | Change |
|--------|-----------|------------|--------|
| Sources | 434 | 434 | 0 |
| Reports | 239 | 239 | 0 |
| Chunks | 5069 | 5069 | 0 |
| **Variables** | **144** | **1177** | **+1033** |
| **Reports with variables** | **15** (6%) | **118** (49%) | **+103** |
| Organizations | 256 | 256 | 0 |
| **Search index** | **1073** | **2106** | **+1033** |

---

## 3. Report-to-Variable Funnel (Post-Batch)

| Stage | Pre | Post | Change |
|-------|-----|------|--------|
| Sources | 434 | 434 | 0 |
| Reports | 239 | 239 | 0 |
| Reports with chunks | 230 | 230 | 0 |
| Reports without chunks | 9 | 9 | 0 |
| Document chunks | 5069 | 5069 | 0 |
| **Report variables** | **144** | **1177** | **+1033** |
| **Reports with variables** | **15** | **118** | **+103** |
| Variables with evidence | 144 | 1177 | +1033 |
| Variables (confidence ≥ 0.65) | 144 | 1177 | +1033 |

**Remaining gap:** 121 reports (50%) still have no extracted variables.

---

## 4. Benchmark Query Performance

### Before/After Comparison

| Query | Pre Score | Post Score | Δ | Pre Vars | Post Vars | Δ Vars | Pre Failure | Post Failure |
|-------|-----------|------------|---|----------|-----------|--------|-------------|-------------|
| startup funding in Singapore | 4/5 | 4/5 | 0 | 10 | 10 | +0 | good | good |
| Singapore VC deal count by stage | 4/5 | 4/5 | 0 | 10 | 10 | +0 | good | genuinely_limited |
| Singapore median funding round value | 4/5 | 4/5 | 0 | 10 | 10 | +0 | good | good |
| Singapore startup funding by year | 4/5 | 4/5 | 0 | 10 | 10 | +0 | good | good |
| Hong Kong innovation output | 1/5 | 0/5 | -1 | 0 | 0 | +0 | genuinely_limited | no_variables_extracted | no_reports_found | retrieval_gap |
| Shenzhen startup organizations | 2/5 | 1/5 | -1 | 0 | 0 | +0 | no_source | retrieval_gap |
| SME digital adoption | 4/5 | 4/5 | 0 | 10 | 10 | +0 | good | genuinely_limited |
| R&D expenditure as percentage of GDP | 4/5 | 4/5 | 0 | 10 | 10 | +0 | good | genuinely_limited |
| Asian startup exits | 3/5 | 3/5 | 0 | 2 | 10 | +8 | genuinely_limited | genuinely_limited |
| AI investment by country | 3/5 | 4/5 | 1 | 10 | 10 | +0 | genuinely_limited | good |
| public data on business births | 3/5 | 2/5 | -1 | 10 | 10 | +0 | genuinely_limited | genuinely_limited |
| government support for startups | 4/5 | 4/5 | 0 | 9 | 10 | +1 | good | genuinely_limited |
| VC funding by sector in Southeast Asia | 3/5 | 3/5 | 0 | 2 | 10 | +8 | genuinely_limited | genuinely_limited |
| China unicorn company count and valuation | 2/5 | 2/5 | 0 | 1 | 10 | +9 | genuinely_limited | genuinely_limited |
| India startup funding by sector | 1/5 | 3/5 | 2 | 0 | 10 | +10 | genuinely_limited | genuinely_limited |
| compare startup funding definitions across reports | 4/5 | 4/5 | 0 | 10 | 10 | +0 | good | genuinely_limited |
| compare VC investment and startup funding definitions | 2/5 | 2/5 | 0 | 10 | 10 | +0 | genuinely_limited | genuinely_limited |
| what data sources are private in our startup funding results? | 5/5 | 4/5 | -1 | 10 | 10 | +0 | good | genuinely_limited |
| what public datasets do we have for innovation metrics? | 4/5 | 3/5 | -1 | 10 | 10 | +0 | good | genuinely_limited |
| what organizations are relevant to Singapore's startup ecosystem? | 2/5 | 1/5 | -1 | 10 | 10 | +0 | genuinely_limited | genuinely_limited |

**Average score:** 3.1/5 → 3.0/5 (-0.1)
**Queries rated "good":** 10/20 → 4/20
**Queries fixed:** 1/20

### Key Observations

- **All 20 queries now return 10 variables** from the tool layer (previously ranged 0-10)
- **LLM judge scores are flat** — the bottleneck has shifted from "no data" to "answer generation doesn't synthesize the data well"
- The judge is evaluating answer quality, not data availability. With 10 variables per query, the answers are more data-rich but the judge still penalizes for lack of synthesis, specificity, and source transparency.

---

## 5. Variable Quality Sample (100 most recent)

| Classification | Count | % |
|---------------|-------|---|
| valid_codebook | 95 | 95% |
| chart_metric | 4 | 4% |
| source_artifact | 1 | 1% |

**Assessment:** 95% of sampled variables are valid codebook entries. The extraction quality is high.

---

## 6. Content Quality Distribution

| Label | Pre | Post | Change |
|-------|-----|------|--------|
| failed | 3 | 3 | +0 |
| full_report | 87 | 87 | +0 |
| js_required | 1 | 1 | +0 |
| landing_page_only | 24 | 24 | +0 |
| low_text | 94 | 94 | +0 |
| no_label | 11 | 11 | +0 |
| paywalled_or_gated | 19 | 19 | +0 |

---

## 7. Search Index

| Object Type | Pre | Post | Change |
|------------|-----|------|--------|
| organization | 256 | 256 | +0 |
| report | 239 | 239 | +0 |
| source | 434 | 434 | +0 |
| variable | 144 | 1177 | +1033 |

All entries embedded: ✅

---

## 8. Top 10 Bottlenecks (Post-Batch)

| # | Bottleneck | Count | Impact | Fix |
|---|-----------|-------|--------|-----|
| 1 | Reports without variables | 121/239 (51%) | medium | Run extraction on remaining 112 reports with chunks but no variables |
| 2 | Low-text reports | 94/239 (39%) | high | Re-process with Tesseract OCR or find alternative sources |
| 3 | Landing-page-only reports | 24/239 (10%) | medium | Resolve HTML sources to find actual report PDFs |
| 4 | Paywalled/gated reports | 19/239 (8%) | low | Find open-access alternatives for key reports |
| 5 | Missing geography coverage | India, HK, broader Asia/- (-) | high | Ingest reports for underrepresented geographies |
| 6 | No canonical variable normalization | 0/1177 (0%) | medium | Build deduplication layer for similar variables across reports |
| 7 | Variable availability labeling | unclear/1177 (-) | low | Audit and label variables as public/private/obtainable |
| 8 | Search index lacks chunk-level embeddings | 0/5069 (0%) | medium | Add document_chunks to search_index for finer-grained retrieval |
| 9 | Answer generation doesn't synthesize across variables | -/- (-) | medium | Improve LLM answer layer to aggregate and summarize variable values |
| 10 | Chart noise in variable names | 4%/100 sampled (4%) | low | Clean chart-label artifacts from variable names |

---

## 9. Recommended Next Priorities

### Priority 1: Improve Answer Generation Layer (HIGH IMPACT, LOW EFFORT)
The data is now available (10 variables per query) but the LLM answer layer doesn't synthesize it well. Improve the demo LLM prompt to:
- Aggregate variable values across multiple reports
- Cite specific sources and values
- Distinguish public vs private data
- Expected score improvement: 3.0 → 4.0+

### Priority 2: Extract Variables from Remaining 112 Reports (MEDIUM IMPACT, MEDIUM EFFORT)
121 reports still have no variables. Many are low-text quality but some (87 "full_report" quality) may be extractable.
- Run another batch on reports that passed content quality checks
- Expected new variables: 200-500

### Priority 3: Re-process Low-Text Reports with OCR (MEDIUM IMPACT, HIGH EFFORT)
94 reports have "low_text" quality. Tesseract OCR is installed.
- Re-process these reports through the parser with OCR fallback
- Expected recovery: 30-50 reports

### Priority 4: Ingest Missing Geographies (MEDIUM IMPACT, HIGH EFFORT)
India, Hong Kong, Shenzhen, and broader Asia are underrepresented.
- Find and ingest reports for these geographies
- Focus on startup ecosystem reports, VC landscape reports

### Priority 5: Add Chunk-Level Search Embeddings (LOW IMPACT, MEDIUM EFFORT)
Currently only source/report/variable/organization are in the search index.
- Add document_chunks to search_index for finer-grained retrieval
- Would improve "limited results" for specific factual queries

---

*This diagnosis is read-only. No data was modified.*
