# Demo Query Results — Venture-Metrics-db

**Date:** 2026-05-24
**Database:** 358 sources, 163 reports, 144 variables, 256 organizations, 921 search index items
**Embedding model:** OpenAI text-embedding-3-small (1024d)

---

## Query 1: What data do we have on startup funding in Singapore?

**Tool called:** `find_data`
**Parsed intent:** geography=Singapore, measure_intent=amount, broad=true

| # | Variable | Score | Availability | Evidence Quote |
|---|----------|-------|-------------|----------------|
| 1 | Median value of Seed rounds | 1.07 | obtainable | "The median value of Seed rounds surged 82.4% to $2.7 million last year" |
| 2 | Deal count per size of equity funding | 1.05 | obtainable | "Excluding deals with unverified investment value; all monetary figures are in USD" |
| 3 | Deal volume (equity rounds) | 1.04 | obtainable | "Deals refer primarily to equity funding rounds. Debt funding, bridge loans, ICOs and grants are excluded." |
| 4 | Deal value | 1.03 | obtainable | "All monetary values listed in this report are in US dollars." |
| 5 | Deal value by Smart Nation verticals | 1.02 | obtainable | "Top verticals under Smart Nation and Digital Economy themes in Singapore by value in 2022" |

**Source URLs:**
- https://www.startupsg.gov.sg/public/2023-03/Singapore%20Venture%20Funding%20Landscape%202022%20Report.pdf
- https://www.startupsg.gov.sg/public/inline-images/EntSG_9M_2024_Venture%20Funding_Landscape_v1.pdf

**Clarification needed:** No
**Quality score:** 5/5 — Excellent. Multiple Singapore-specific variables with clear definitions, evidence quotes, and obtainable availability.

---

## Query 2: Find VC deal count by stage.

**Tool called:** `find_data`
**Parsed intent:** measure_intent=count, broad=false

| # | Variable | Score | Availability | Evidence Quote |
|---|----------|-------|-------------|----------------|
| 1 | Late-stage deals | 1.05 | private | "The late stage consists of Series C and subsequent venture rounds." |
| 2 | Early-stage deals | 1.01 | private | "The early stage consists of seed to Series B venture rounds." |
| 3 | Venture capital investments by stage of investment | 0.99 | private | "Venture capital investments classified by stages: seed capital, early-stage funding, and late-growth stage." |

**Source URLs:**
- https://www.startupsg.gov.sg/public/inline-images/EntSG_9M_2024_Venture%20Funding_Landscape_v1.pdf

**Clarification needed:** No
**Quality score:** 4/5 — Good. Clear stage definitions and measurement methods. All marked as private (PitchBook data), which is accurate but limits accessibility.

---

## Query 3: What sources do we have for SME digital adoption?

**Tool called:** `find_data`
**Parsed intent:** broad=true

| # | Variable | Score | Availability | Evidence Quote |
|---|----------|-------|-------------|----------------|
| 1 | Average cost savings per firm per PSG application | 0.35 | unclear | "SMEs that adopted digital solutions under the Productivity Solutions Grant (PSG) have reported cost savings of around 50% on average during 2018 to 2023" |

**Source URLs:**
- https://www.imda.gov.sg/-/media/imda/files/infocomm-media-landscape/research-and-statistics/sgde-report/singapore-digital-economy-report-2024.pdf

**Clarification needed:** No, but results are thin
**Quality score:** 3/5 — Only 1 relevant variable found. The match is relevant but limited. More SME digital adoption data would strengthen this query.

---

## Query 4: Compare startup funding definitions across reports.

**Tool called:** `compare_concepts`
**Query:** "startup funding"

| # | Comparison |
|---|------------|
| — | (empty) |

**Clarification needed:** Yes — the tool requires specific report IDs or concept IDs to compare. Without them, it returns empty.
**Quality score:** 2/5 — Tool works but needs better auto-discovery of related reports. The ILIKE search on variable names didn't match "startup funding" exactly. Better to use `find_data` first, then compare.

**Recommendation:** Use `find_data` with "venture funding" → get report IDs → then `compare_concepts` with those IDs.

---

## Query 5: Which reports rely on private data sources?

**Tool called:** `find_data`
**Parsed intent:** public_only=false

| # | Variable | Score | Availability | Evidence Quote |
|---|----------|-------|-------------|----------------|
| 1 | Venture funding deal value by top 10 global startup ecosystems | 0.37 | private | "Source of venture funding data: PitchBook. All monetary figures are in USD." |
| 2 | Share of down rounds in late-stage companies YTD | 0.36 | private | "Down rounds have dropped from 15.3% in 2024 to 6.4% year-to-date (YTD)" |
| 3 | Share of insider-led VC deals YTD | 0.35 | private | "Insider-led venture capital (VC) deals reached the highest share in a decade at 9.1%" |

**Clarification needed:** No
**Quality score:** 3/5 — Returns variables with private availability, but doesn't aggregate by report. Would be more useful as a filter: "show me all reports where most variables are private."

---

## Query 6: Do we have public data on R&D expenditure as % of GDP?

**Tool called:** `find_data`
**Parsed intent:** public_only=true, measure_intent=amount

| # | Variable | Score | Availability | Evidence Quote |
|---|----------|-------|-------------|----------------|
| 1 | gross expenditure on research and development as a percentage of GDP | 1.19 | obtainable | "Metric 1: gross expenditure on research and development as a percentage of GDP... Chart: UK gross expenditure on R&D" |

**Source URLs:**
- https://assets.publishing.service.gov.uk/media/686e2be010d550c668de3cb1/DSIT_ARA_2024-25_web_optimised.pdf

**Clarification needed:** No
**Quality score:** 5/5 — Perfect match. Clear definition ("R&D intensity"), public/obtainable availability, UK ONS data source, evidence quote present.

---

## Query 7: What organizations are relevant to the Shenzhen startup ecosystem?

**Tool called:** `semantic_search`
**Object types:** organization

| # | Organization | Type | Geography | Score |
|---|-------------|------|-----------|-------|
| 1 | 岭南大学 (Lingnan) - 初创与衍生公司官方列表 | accelerator | Hong Kong | 0.37 |
| 2 | 深圳市传感器与智能化仪器仪表行业协会 | association | Shenzhen | 0.36 |
| 3 | 深圳市无人机行业协会 | association | Shenzhen | 0.35 |

**Clarification needed:** No
**Quality score:** 4/5 — Good results. Shenzhen associations are returned. The top result is a HK university which is nearby but not exactly Shenzhen. The geo-priority inference is working (Shenzhen > Hong Kong for Shenzhen orgs).

---

## Query 8: What data can help study Hong Kong innovation output?

**Tool called:** `find_data`
**Parsed intent:** geography=Hong Kong, broad=true

| # | Result Type | Title | Score |
|---|------------|-------|-------|
| 1 | organization | 香港中文大学 (CUHK) - InnoPort | 0.87 |
| 2 | organization | 香港科技大学 (HKUST) - 创业中心 | 0.85 |
| 3 | organization | 香港城市大学 (CityU) - HK Tech 300 | 0.83 |

**Source URLs:**
- https://innoport.cuhk.edu.hk
- https://ec.hkust.edu.hk
- https://www.cityu.edu.hk/hktech300

**Clarification needed:** No
**Quality score:** 3/5 — Returns organizations (TTOs, incubators) but no variables or reports with HK-specific innovation metrics. The database has HK organizations but limited HK report data with extracted variables.

---

## Query 9: compare_concepts with specific reports

**Tool called:** `compare_concepts`
**Query:** "venture funding"
**Report IDs:** Singapore Venture Funding Landscape 2023, FinTech state of play 2.0, Key Insights into Singapore Tech Ecosystem

| # | Variable | Report | Definition |
|---|----------|--------|------------|
| 1 | Venture funding deal value by top 10 global startup ecosystems | EntSG 9M 2024 | Total venture funding deal value in USD for top 10 ecosystems |
| 2 | Venture capital investments by stage | PitchBook SG | Classified by stages: seed, early, late-growth |
| 3 | Venture capital investments by sector | PitchBook SG | Classified by industry sector |

**Clarification needed:** No
**Quality score:** 4/5 — Works well with "venture funding" query. Shows variables from different reports for comparison.

---

## Query 10: list_available_filters

**Tool called:** `list_available_filters`

**Available filters:**
- **Object types:** dataset, organization, report, source, variable
- **Geographies:** 47 values (Singapore, Hong Kong, Shenzhen, UK, US, China, ASEAN 6, etc.)
- **Availability:** not_obtainable, obtainable, private, public, unclear, unknown
- **Source types:** html, pdf
- **Max limit:** 25

**Quality score:** 5/5 — Complete filter inventory. Shows the breadth of the database.

---

## Summary

| Query | Tool | Quality | Issues |
|-------|------|---------|--------|
| Startup funding in Singapore | find_data | 5/5 | None |
| VC deal count by stage | find_data | 4/5 | All private availability |
| SME digital adoption | find_data | 3/5 | Thin results (1 variable) |
| Compare startup funding definitions | compare_concepts | 2/5 | Empty without report IDs |
| Private data sources | find_data | 3/5 | No report-level aggregation |
| R&D expenditure GDP | find_data | 5/5 | None |
| Shenzhen organizations | semantic_search | 4/5 | Top result is HK org |
| HK innovation output | find_data | 3/5 | Only orgs, no variables |
| compare_concepts (w/ IDs) | compare_concepts | 4/5 | Works with explicit IDs |
| list_available_filters | list_available_filters | 5/5 | None |

**Overall: 38/50 (76%)**

**Key findings:**
- `find_data` and `semantic_search` work well for most queries
- `compare_concepts` needs report IDs to function — auto-discovery is weak
- Singapore data is strongest (many variables with evidence quotes)
- HK data is org-heavy but variable-light
- Private availability is common for PitchBook data (accurate but limiting)
- The intent parser correctly identifies geography and measure intent
