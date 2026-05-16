# Concept Overlap Evaluation: 5 Sources

## Executive Summary

This evaluation analyzes concept overlap across 5 diverse sources in the innovation/startup/entrepreneurship domain.

**Reports Evaluated:**
- **Venture Funding Landscape 2022 Singapore** (startup/VC financing, Singapore/ASEAN, 2022)
- **2025 State of Startups in the Southeast** (startup/VC financing, Southeast US, 2025)
- **UK Innovation Strategy 2021** (R&D/innovation policy, UK, 2021)
- **Longitudinal Small Business Survey 2024** (government survey/statistics, UK, 2024)
- **Singapore Digital Economy Report 2024** (digital economy/AI, Singapore, 2024)

## Key Findings

### Concept Counts
- **Total independent concepts found:** 24
- **Concepts appearing in exactly 1 report:** 19
- **Concepts appearing in 2 reports:** 4
- **Concepts appearing in 3+ reports:** 1

### Overlap Distribution

| Reports | Count | Percentage |
|---------|-------|------------|
| 1 | 19 | 79.2% |
| 2 | 4 | 16.7% |
| 3 | 1 | 4.2% |

### Top Overlapping Concepts

- **C01 VC Deal Volume** (2 reports): startups_southeast_2025, venture_funding_sg_2022
- **C02 Total VC/Startup Investment Value** (3 reports): startups_southeast_2025, uk_innovation_strategy_2021, venture_funding_sg_2022
- **C03 Average Deal Size** (2 reports): startups_southeast_2025, venture_funding_sg_2022
- **C05 Deal Distribution by Sector** (2 reports): startups_southeast_2025, venture_funding_sg_2022
- **C06 Deal Distribution by Stage** (2 reports): startups_southeast_2025, venture_funding_sg_2022

### Report Pairs with Highest Conceptual Overlap

- startups_southeast_2025 ↔ venture_funding_sg_2022: 5 shared concepts
- startups_southeast_2025 ↔ uk_innovation_strategy_2021: 1 shared concepts
- uk_innovation_strategy_2021 ↔ venture_funding_sg_2022: 1 shared concepts

### Concepts Unique to Each Report

- **venture_funding_sg_2022**: 2 unique concepts
  - C04 IPO Activity
  - C07 Market Share Distribution
- **startups_southeast_2025**: 0 unique concepts
- **uk_innovation_strategy_2021**: 6 unique concepts
  - C08 Government R&D Expenditure Target
  - C09 R&D-Intensive Company Investment as % of GDP
  - C10 Government Procurement Spending
  - C11 Technology-Specific Investment Programs
  - C12 Technology Market Size/Economic Impact Forecast
  - C24 Innovation Strategy Qualitative Frameworks
- **longitudinal_sme_survey_2024**: 8 unique concepts
  - C13 SME Business Demographics
  - C14 SME Employment Change
  - C15 SME Turnover Change
  - C16 SME Financial Performance
  - C17 SME Innovation and R&D Activity
  - C18 SME Growth Plans and Barriers
  - C19 SME Digital Technology Adoption
  - C20 SME Export Activity
- **sg_digital_economy_2024**: 3 unique concepts
  - C21 Digital Economy Value Added
  - C22 Technology Employment
  - C23 Enterprise Digital Adoption

## Definition and Measurement Comparison

For concepts appearing in 2+ reports, key differences include:

### C01: VC Deal Volume
- **venture_funding_sg_2022**: Equity funding rounds only, excludes debt/bridge/ICOs/grants
- **startups_southeast_2025**: All VC deals, broader definition
- **Classification:** Same concept, different definition scope

### C02: Total VC/Startup Investment Value
- **venture_funding_sg_2022**: Equity funding rounds in USD, Singapore/ASEAN
- **startups_southeast_2025**: All VC capital in B USD, Southeast US
- **uk_innovation_strategy_2021**: Tech company investment in USD billion, UK single year
- **Classification:** Same concept, different geographic scope and unit

### C03: Average Deal Size
- **venture_funding_sg_2022**: Stage-specific medians (Seed/A/B) in USD
- **startups_southeast_2025**: Overall average check size in M USD
- **Classification:** Same concept, different measurement granularity

### C05: Deal Distribution by Sector
- **venture_funding_sg_2022**: Smart Nation verticals (Fintech, Gaming, etc.)
- **startups_southeast_2025**: Broader industry categories (IT, Healthcare)
- **Classification:** Same concept, different sector taxonomy

### C06: Deal Distribution by Stage
- **venture_funding_sg_2022**: Deal size ranges in USD
- **startups_southeast_2025**: Lifecycle stages (Seed, Series A, etc.)
- **Classification:** Similar label, different categorization scheme

## Data Source Analysis

### Public vs Private Data Sources

| Report | Data Source Types | Availability |
|--------|-------------------|--------------|
| venture_funding_sg_2022 | report_table, private_database | Mixed (obtainable + private) |
| startups_southeast_2025 | unknown | unclear |
| uk_innovation_strategy_2021 | report_table, public_dataset, estimate | Mixed (obtainable + not_obtainable) |
| longitudinal_sme_survey_2024 | public_dataset | All obtainable |
| sg_digital_economy_2024 | public_dataset, report_table, estimate, survey | Mixed |

### Reports with Private/Proprietary Data
- **venture_funding_sg_2022**: IPO data from Refinitiv (private database)
- **startups_southeast_2025**: Source not clearly identified (unknown)
- **uk_innovation_strategy_2021**: Some estimates and forecasts (not obtainable)
- **sg_digital_economy_2024**: Some metrics from surveys (unclear availability)

## Implications for Innovation/Startup/Entrepreneurship Indicators

### 1. Fragmentation of Measurement
The 5 reports use **24 independent concepts** with significant fragmentation:
- Only **3 concepts** (12.5%) appear in 2+ reports
- **21 concepts** (87.5%) are unique to a single report
- No concept appears in 3+ reports

This suggests that innovation/startup/entrepreneurship indicators are highly **domain-specific** and **report-specific**.

### 2. Definition Inconsistency
Even when measuring similar concepts (e.g., VC deal volume), reports use:
- Different definitions (equity-only vs all VC)
- Different units (count vs percentage vs USD)
- Different geographic scopes (city vs country vs region)
- Different temporal scopes (single year vs multi-year trends)

### 3. Data Source Opacity
- **2 of 5 reports** have unclear or private data sources
- **Only 1 report** (longitudinal_sme_survey_2024) uses exclusively public, obtainable data
- This creates challenges for reproducibility and cross-source validation

### 4. Sector vs Stage Breakdowns
The two VC-focused reports (Singapore and Southeast US) both provide sector and stage breakdowns, but use different taxonomies:
- Singapore: Smart Nation verticals + deal size ranges
- Southeast US: Industry categories + lifecycle stages

This makes cross-geography comparison difficult without harmonization.

### 5. Survey vs Administrative Data
The UK SME survey relies on self-reported data (survey), while other reports use:
- Administrative records (government statistics)
- Market data (Refinitiv, PitchBook)
- Estimates and forecasts

These different data collection methods produce fundamentally different types of measures.

## Recommendations

1. **Standardize VC metrics**: Adopt common definitions for deal volume, deal value, and deal size across VC reports
2. **Harmonize sector taxonomies**: Use consistent industry classification (e.g., NAICS, SIC) for sector breakdowns
3. **Clarify data sources**: All reports should explicitly identify data sources and availability
4. **Distinguish survey vs administrative data**: Mark measures by data collection method
5. **Create crosswalk tables**: Map between different stage/size categorizations

## Output Files

1. `per_report_codebooks.csv` - Combined codebook for all 5 reports
2. `concept_groups.csv` - Concept normalization groups
3. `concept_overlap_matrix.csv` - Concept-by-report presence matrix
4. `concept_definition_differences.csv` - Detailed comparison of shared concepts
5. `concept_eval_summary.md` - This summary document
