# Research Task Execution Layer — Quality Assessment

Generated: 2026-05-28

---

## 1. Executive Summary

The new Research Task Execution layer (ResearchTaskPlanner, EvidencePacketBuilder, AnswerSynthesizer, ComparabilityValidator, TableExcelExportService) was evaluated on **21 queries** across 4 groups.

**Overall LLM judge score: 2.29/5** (vs previous benchmark 3.0/5)

| Group | Avg Score | Queries |
|-------|-----------|---------|
| A_normal | 3.17/5 | 6 |
| B_clarification | 2.20/5 | 5 |
| C_export | 2.40/5 | 5 |
| D_comparability | 1.20/5 | 5 |

**Key findings:**
- **Normal answer synthesis (Group A): 3.2/5** — decent, concept grouping works
- **Clarification (Group B): 2.2/5** — mixed; vague queries return data when they shouldn't
- **Export (Group C): 2.4/5** — exports work but answers don't synthesize well
- **Comparability (Group D): 1.2/5** — weakest; aggregation safety works but answers are confusing

**Improvement over previous layer:** 11/21 queries rated "better", 10/21 "worse"

---

## 2. Answer Quality (Group A: Normal Synthesis)

| # | Query | Task Type | Vars | Direct | Score | Failure |
|---|-------|-----------|------|--------|-------|---------|
| 1 | startup funding in Singapore | simple_answer | 25 | 25 | 4/5 | good |
| 2 | Singapore VC deal count by stage | simple_answer | 25 | 25 | 2/5 | answer_generation_gap |
| 3 | Singapore median funding round value | simple_answer | 25 | 25 | 3/5 | answer_generation_gap |
| 4 | R&D expenditure as percentage of GDP | simple_answer | 25 | 24 | 3/5 | answer_generation_gap |
| 5 | SME digital adoption | simple_answer | 25 | 0 | 3/5 | answer_generation_gap |
| 6 | government support for startups | simple_answer | 25 | 4 | 4/5 | good |

**Strengths:**
- Concept grouping works well (stage breakdown, funding amount, deal activity)
- Direct vs contextual match distinction is useful
- 25 variables retrieved per query (max limit)

**Weaknesses:**
- Answers are formulaic — "Direct answer: I found X direct and Y contextual matches"
- No actual synthesis of values (doesn't say "Singapore VC deal count was X in year Y")
- Source transparency is low — lists report titles but doesn't quote specific values
- The answer reads like a structured data dump, not a research answer

---

## 3. Clarification Quality (Group B: Vague Queries)

| # | Query | Task Type | Vars | Clarification Asked | Score | Failure |
|---|-------|-----------|------|---------------------|-------|---------|
| 7 | startup data | find_data | 25 | False | 4/5 | none |
| 8 | innovation ecosystem in Asia | simple_answer | 0 | True | 0/5 | no_data |
| 9 | funding trends | simple_answer | 25 | False | 4/5 | none |
| 10 | analyze Singapore startups | simple_answer | 25 | False | 3/5 | answer_generation_gap |
| 11 | make me a dataset on Asian startups | build_table | 0 | True | 0/5 | no_data |

**Issues:**
- "innovation ecosystem in Asia" returns 0 results and says "could not find" — should ask what aspect (VC? research output? organizations?)
- "make me a dataset on Asian startups" correctly triggers build_table but returns empty — should ask for geography/metric scope
- "startup data" and "funding trends" return 25 variables — too broad, should ask for refinement
- No explicit clarification mechanism — the system either finds data or says "could not find"

**Fix needed:** Add a clarification step when:
1. Query is too broad (>15 variables returned, no geography/time filter)
2. Query returns 0 results
3. Query is ambiguous (multiple possible interpretations)

---

## 4. Export Quality (Group C: Table/Excel Generation)

| # | Query | Format | Rows | File Exists | Size | Score |
|---|-------|--------|------|-------------|------|-------|
| 12 | Create an Excel of Singapore startup funding by stage | xlsx | 25 | True | 25435 | 3/5 |
| 13 | Create a table of Singapore median funding round values | csv | 25 | True | 23106 | 2/5 |
| 14 | Build an Excel of public innovation metrics | xlsx | 25 | True | 25425 | 3/5 |
| 15 | Create a source comparison table for startup funding reports | csv | 25 | True | 23125 | 1/5 |
| 16 | Export a dataset of SME digital adoption variables | csv | 25 | True | 22779 | 3/5 |

**Export structure (xlsx files):**
- Sheet 1: `normalized_data` — 15 columns (metric_name, geography, time_period, value, unit, source_report, availability, etc.)
- Sheet 2: `source_variables` — raw variable data
- Sheet 3: `source_reports` — report metadata
- Sheet 4: `methodology_notes` — query, task type, method, comparability status
- Sheet 5: `data_gaps` — missing metadata

**Strengths:**
- Files are created correctly
- Normalized data structure is well-designed
- Methodology notes are informative
- Data gaps sheet is a good addition

**Weaknesses:**
- Value extraction from evidence quotes is hit-or-miss (many null values)
- Doesn't include actual numeric data from the database (only what's in evidence quotes)
- Source comparison table doesn't actually compare sources side-by-side

---

## 5. Comparability Quality (Group D: Aggregation Safety)

| # | Query | Status | Can Aggregate | Issues | Score |
|---|-------|--------|---------------|--------|-------|
| 17 | Add up startup funding across Singapore reports | not_comparable | False | Mixed geography: asean, asean, singapore, global, top 10 ecosystems, singapore,  | 2/5 |
| 18 | Aggregate VC deal counts from all available sources | not_comparable | False | Mixed geography: americas, asean-6 countries, global, multiple countries includi | 2/5 |
| 19 | Compare startup funding amount vs VC investment definitions | not_comparable | False | Missing geography metadata.; Missing time period metadata.; Mixed unit: $, %. | 1/5 |
| 20 | Can we combine IPO proceeds with startup funding? | not_comparable | False | Mixed geography: cairo, mena, global, mena, north america and global, north amer | 1/5 |
| 21 | Create a single Asia startup exits dataset from all reports | insufficient_metadata | False | No rows available for comparison. | 0/5 |

**Comparability validation works correctly:**
- Detects mixed geography, time periods, units, definitions
- Correctly blocks aggregation when data is not comparable
- Returns `not_comparable` status for aggregation requests

**Issues:**
- The answer doesn't explain WHY aggregation is blocked in user-friendly terms
- The answer says "not comparable" but doesn't offer a comparison table instead
- When aggregation is blocked, should still show the data in a structured way
- The comparability validator is conservative — even same-metric data from different reports gets flagged

---

## 6. Task Type Performance

| Task Type | Count | Avg Score | Notes |
|-----------|-------|-----------|-------|
| find_data | 1 | 4.00/5 | |
| create_excel | 2 | 3.00/5 | |
| simple_answer | 10 | 2.70/5 | |
| aggregate_values | 2 | 2.00/5 | |
| build_table | 5 | 1.20/5 | |
| compare_definitions | 1 | 1.00/5 | |

---

## 7. Generated Artifacts

7 files generated in `/data/hermes/exports/eval/`:

| Query | Format | Exists | Size |
|-------|--------|--------|------|
| make me a dataset on Asian startups |  | ✅ | 183 bytes |
| Create an Excel of Singapore startup funding by st |  | ✅ | 25435 bytes |
| Create a table of Singapore median funding round v |  | ✅ | 23106 bytes |
| Build an Excel of public innovation metrics |  | ✅ | 25425 bytes |
| Create a source comparison table for startup fundi |  | ✅ | 23125 bytes |
| Export a dataset of SME digital adoption variables |  | ✅ | 22779 bytes |
| Create a single Asia startup exits dataset from al |  | ✅ | 183 bytes |

---

## 8. Comparison vs Previous Answer Layer

| Dimension | Previous (post-batch) | New Layer | Change |
|-----------|----------------------|-----------|--------|
| Avg LLM score | 3.0/5 | 2.29/5 | -0.71 |
| Variables per query | 10 | 21.2 | +11.2 |
| Concept grouping | ❌ | ✅ | New |
| Direct/contextual split | ❌ | ✅ | New |
| Comparability validation | ❌ | ✅ | New |
| Excel/CSV export | ❌ | ✅ | New |
| Methodology notes | ❌ | ✅ | New |
| Data gaps reporting | ❌ | ✅ | New |
| Value synthesis | ❌ | Partial | Needs work |
| Clarification | ❌ | ❌ | Not implemented |

**Assessment:** The new layer adds significant structural improvements (concept grouping, comparability, exports) but the **answer synthesis quality dropped** because the template-based answers don't actually extract and present values from the data. The previous layer's LLM-generated answers were more natural but less structured.

---

## 9. Product-Readiness Assessment

### Is the Research Task Execution layer product-ready?

**Partially.** The infrastructure is solid but the answer quality needs improvement before production.

### What works well?
1. ✅ ResearchTaskPlanner correctly classifies task types
2. ✅ EvidencePacketBuilder structures data well
3. ✅ ComparabilityValidator correctly blocks unsafe aggregation
4. ✅ Excel exports are well-structured with methodology notes
5. ✅ Concept grouping and direct/contextual split are useful
6. ✅ Data gaps reporting is informative

### What fails?
1. ❌ AnswerSynthesizer produces template-like answers, not research-quality
2. ❌ No clarification mechanism for vague/empty queries
3. ❌ Value extraction from evidence quotes is unreliable
4. ❌ Export files exist but many values are null
5. ❌ Comparability answers don't explain WHY aggregation is blocked
6. ❌ Vague queries return data when they should ask for refinement

---

## 10. Top 10 Fixes

| # | Fix | Impact | Effort | Priority |
|---|-----|--------|--------|----------|
| 1 | **Improve AnswerSynthesizer** — Use LLM to generate natural answers from evidence packets, not templates | HIGH | MEDIUM | P0 |
| 2 | **Add clarification step** — When query is too broad (0 results or >20 results) or ambiguous, ask for refinement | HIGH | MEDIUM | P0 |
| 3 | **Fix value extraction** — Pull actual numeric values from report_variables table, not just evidence quotes | HIGH | MEDIUM | P0 |
| 4 | **Improve comparability answers** — Explain WHY aggregation is blocked, show comparison table instead | MEDIUM | LOW | P1 |
| 5 | **Add data availability to exports** — Mark each row as public/private/obtainable | MEDIUM | LOW | P1 |
| 6 | **Fix export value population** — Many cells are null; populate from database | MEDIUM | MEDIUM | P1 |
| 7 | **Add source comparison logic** — For "source comparison" queries, actually compare sources side-by-side | MEDIUM | HIGH | P2 |
| 8 | **Improve vague query handling** — "startup data" should ask what type, not return 25 random variables | MEDIUM | LOW | P1 |
| 9 | **Add confidence-based filtering** — Don't show low-confidence matches as "direct" | LOW | LOW | P2 |
| 10 | **Add time/geography filtering to exports** — Filter by query's geography/time intent | LOW | MEDIUM | P2 |

---

*This assessment is read-only. No data was modified.*
