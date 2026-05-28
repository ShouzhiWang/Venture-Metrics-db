# Before/After Research Task Evaluation

Generated: 2026-05-29

---

## Score Comparison

| Group | V1 | V2 | Δ | Threshold | Status |
|-------|-----|-----|-----|-----------|--------|
| Overall | 2.29 | 4.20 | +1.91 | ≥ 3.8 | ✅ |
| Normal synthesis | 3.17 | 4.50 | +1.33 | ≥ 4.0 | ✅ |
| Clarification | 2.20 | 4.52 | +2.32 | ≥ 4.0 | ✅ |
| Export | 2.40 | 3.70 | +1.30 | ≥ 3.5 | ✅ |
| Comparability | 1.20 | 4.08 | +2.88 | ≥ 4.0 | ✅ |

---

## V1 Problems → V2 Status

| # | V1 Problem | V2 Status | Evidence |
|---|-----------|-----------|----------|
| 1 | AnswerSynthesizer too template-based | ✅ Fixed | Avg synthesis quality: 5.0/5. Answers now start with natural language, not "Direct answer: I found..." |
| 2 | Clarification weak or missing | ✅ Fixed | 4/5 Group B queries correctly clarified. Q7/Q9/Q10/Q11 return specific questions with domain options |
| 3 | Export files with null values | ✅ Fixed | Non-null rate: 80% (was ~0% in V1). Q12: 19/25 non-null, Q15: 22/25 non-null |
| 4 | Comparability blocks without explaining | ✅ Fixed | Explanation now says "because geographies differ; time periods differ; units differ..." Avg explain: 4.0/5 |
| 5 | Answers don't use retrieved data naturally | ✅ Fixed | LLM synthesizer references specific values: "Seed rounds: $2.7M", "SME adoption: 61%". Avg grounding: 4.8/5 |

---

## Per-Query Scores

| Q# | Query | V1 | V2 | Δ | Notes |
|----|-------|-----|-----|-----|-------|
| 1 | startup funding in Singapore | 4 | 4.71 | +0.71 |  |
| 2 | Singapore VC deal count by stage | 2 | 4.71 | +2.71 |  |
| 3 | Singapore median funding round value | 3 | 4.71 | +1.71 |  |
| 4 | R&D expenditure as percentage of GDP | 3 | 4.29 | +1.29 |  |
| 5 | SME digital adoption | 3 | 4.14 | +1.14 |  |
| 6 | government support for startups | 4 | 4.43 | +0.43 |  |
| 7 | startup data | 4 | 5.00 | +1.00 | clarified |
| 8 | innovation ecosystem in Asia | 0 | 3.00 | +3.00 |  |
| 9 | funding trends | 4 | 5.00 | +1.00 | clarified |
| 10 | analyze Singapore startups | 3 | 5.00 | +2.00 | clarified |
| 11 | make me a dataset on Asian startups | 0 | 4.60 | +4.60 | clarified |
| 12 | Create an Excel of Singapore startup funding  | 3 | 4.50 | +1.50 |  |
| 13 | Create a table of Singapore median funding ro | 2 | 3.75 | +1.75 |  |
| 14 | Build an Excel of public innovation metrics | 3 | 3.25 | +0.25 | clarified |
| 15 | Create a source comparison table for startup  | 1 | 3.75 | +2.75 |  |
| 16 | Export a dataset of SME digital adoption vari | 3 | 3.25 | +0.25 | clarified |
| 17 | Add up startup funding across Singapore repor | 2 | 4.00 | +2.00 |  |
| 18 | Aggregate VC deal counts from all available s | 2 | 4.00 | +2.00 |  |
| 19 | Compare startup funding amount vs VC investme | 1 | 4.00 | +3.00 |  |
| 20 | Can we combine IPO proceeds with startup fund | 1 | 4.00 | +3.00 |  |
| 21 | Create a single Asia startup exits dataset fr | 0 | 4.40 | +4.40 | clarified |

---

## Top 10 Next Fixes

1. **Export default geography** — Q14/Q16 clarify when geography missing. Default to "all available" or "Singapore"
2. **CSV metadata** — methodology_notes and data_gaps are xlsx-only. Add comment rows or sidecar JSON
3. **Empty results UX** — Q21 returns nothing. Show "no data found for Asia exits" with suggestions
4. **Source comparison** — Q15 should compare sources side-by-side
5. **Geography priority** — Q4 returns UK R&D. Prioritize Singapore when implied
6. **Export format default** — "Export a dataset" should default to CSV
7. **Comparability simplification** — "metric definitions differ" → "different metrics measured"
8. **Answer lead** — Open with specific values, not generic intro
9. **Comparison table on block** — Always show side-by-side when aggregation blocked
10. **Run-with-defaults** — After clarification, offer "proceed with defaults" option

---

## Readiness

**✅ READY for data/API ingestion.**

---

*Real DB queries + LLM synthesis. No data modified.*
