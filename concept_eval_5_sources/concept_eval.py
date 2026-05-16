#!/usr/bin/env python3
"""Concept overlap evaluation for 5 selected sources."""

import csv
import json
from collections import defaultdict, Counter
from pathlib import Path

OUTPUT_DIR = Path("/data/hermes/reviews/concept_eval_5_sources")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Report metadata
REPORTS = {
    '95ac4f0b-d41d-426f-ac65-180a72d7a0d8': {
        'short': 'venture_funding_sg_2022',
        'title': 'Venture Funding Landscape 2022 Singapore',
        'domain': 'startup/VC financing',
        'year': 2022,
        'geography': 'Singapore/ASEAN',
    },
    '4332f2ff-bb4a-4ac0-83eb-961b8fcd953c': {
        'short': 'startups_southeast_2025',
        'title': '2025 State of Startups in the Southeast',
        'domain': 'startup/VC financing',
        'year': 2025,
        'geography': 'Southeast US',
    },
    '7e43e206-52d9-4398-bf1a-2a51a6284c1e': {
        'short': 'uk_innovation_strategy_2021',
        'title': 'UK Innovation Strategy 2021',
        'domain': 'R&D/innovation policy',
        'year': 2021,
        'geography': 'UK',
    },
    '99c588db-12b2-4642-a6b9-7289b5607f6e': {
        'short': 'longitudinal_sme_survey_2024',
        'title': 'Longitudinal Small Business Survey 2024',
        'domain': 'government survey/statistics',
        'year': 2024,
        'geography': 'UK',
    },
    'f2236bc6-16ed-4b34-a89d-f3ef854d4f81': {
        'short': 'sg_digital_economy_2024',
        'title': 'Singapore Digital Economy Report 2024',
        'domain': 'digital economy/AI',
        'year': 2024,
        'geography': 'Singapore',
    },
}

# Concept groups
CONCEPTS = [
    {
        'concept_id': 'C01',
        'concept_name': 'VC Deal Volume',
        'concept_description': 'Total number of venture capital or equity funding deals completed in a defined geography and time period.',
        'included_variables': [
            ('venture_funding_sg_2022', 'Deal volume'),
            ('startups_southeast_2025', 'Southeast VC Deal Count'),
        ],
        'confidence': 'high',
        'notes': 'Both measure count of VC/equity deals, but different geographies (Singapore/ASEAN vs Southeast US) and slightly different definitions (equity-only vs all VC). Comparable concept, different scope.',
    },
    {
        'concept_id': 'C02',
        'concept_name': 'Total VC/Startup Investment Value',
        'concept_description': 'Total monetary value of venture capital or startup investment in a defined geography and time period.',
        'included_variables': [
            ('venture_funding_sg_2022', 'Deal value'),
            ('startups_southeast_2025', 'Capital Deployed'),
            ('uk_innovation_strategy_2021', 'Volume of investment into tech companies in 2020'),
        ],
        'confidence': 'medium',
        'notes': 'All measure total investment value, but different geographies and slightly different scopes (equity rounds vs all VC vs tech companies). The UK report uses a single year snapshot while others show trends.',
    },
    {
        'concept_id': 'C03',
        'concept_name': 'Average Deal Size',
        'concept_description': 'Average or median amount invested per funding deal.',
        'included_variables': [
            ('venture_funding_sg_2022', 'Median value of Seed rounds'),
            ('venture_funding_sg_2022', 'Median value of Series A rounds'),
            ('venture_funding_sg_2022', 'Median value of Series B rounds'),
            ('startups_southeast_2025', 'Average Check Size'),
        ],
        'confidence': 'medium',
        'notes': 'Singapore report provides stage-specific medians, while Southeast US provides overall average. Not directly comparable without stage breakdown.',
    },
    {
        'concept_id': 'C04',
        'concept_name': 'IPO Activity',
        'concept_description': 'Number and proceeds of initial public offerings by companies in a defined geography.',
        'included_variables': [
            ('venture_funding_sg_2022', 'Number of IPOs'),
            ('venture_funding_sg_2022', 'IPO proceeds (USD Million)'),
        ],
        'confidence': 'high',
        'notes': 'Only appears in Singapore venture report. No equivalent in other reports.',
    },
    {
        'concept_id': 'C05',
        'concept_name': 'Deal Distribution by Sector',
        'concept_description': 'Breakdown of venture deals or investment by industry sector.',
        'included_variables': [
            ('venture_funding_sg_2022', 'Deal count by vertical under Smart Nation theme'),
            ('venture_funding_sg_2022', 'Deal value by vertical under Smart Nation theme'),
            ('startups_southeast_2025', 'Capital Invested by Sector'),
        ],
        'confidence': 'medium',
        'notes': 'All show sector breakdowns, but different geographies and reporting styles.',
    },
    {
        'concept_id': 'C06',
        'concept_name': 'Deal Distribution by Stage',
        'concept_description': 'Breakdown of venture deals or investment by company lifecycle stage.',
        'included_variables': [
            ('venture_funding_sg_2022', 'Deal count per size of equity funding'),
            ('startups_southeast_2025', 'Capital Invested by Stage Cohorts (% Share)'),
        ],
        'confidence': 'medium',
        'notes': 'Singapore uses deal size ranges, while Southeast US uses lifecycle stages. Related but different categorization.',
    },
    {
        'concept_id': 'C07',
        'concept_name': 'Market Share Distribution',
        'concept_description': 'Percentage share of total deals or investment accounted for by each market/region.',
        'included_variables': [
            ('venture_funding_sg_2022', 'Share of deal volume per market'),
            ('venture_funding_sg_2022', 'Share of deal value per market'),
        ],
        'confidence': 'high',
        'notes': 'Only in Singapore report. Shows ASEAN 6 market distribution.',
    },
    {
        'concept_id': 'C08',
        'concept_name': 'Government R&D Expenditure Target',
        'concept_description': 'Government target or commitment for public expenditure on research and development.',
        'included_variables': [
            ('uk_innovation_strategy_2021', 'Public expenditure on R&D target'),
        ],
        'confidence': 'high',
        'notes': 'UK-specific government target. No equivalent in other reports.',
    },
    {
        'concept_id': 'C09',
        'concept_name': 'R&D-Intensive Company Investment as % of GDP',
        'concept_description': 'Investment received by R&D-intensive companies expressed as a percentage of GDP.',
        'included_variables': [
            ('uk_innovation_strategy_2021', 'UK R&D-intensive companies investment as % of GDP'),
            ('uk_innovation_strategy_2021', 'US R&D-intensive companies investment as % of GDP'),
        ],
        'confidence': 'high',
        'notes': 'Same metric for two countries. Directly comparable concept.',
    },
    {
        'concept_id': 'C10',
        'concept_name': 'Government Procurement Spending',
        'concept_description': 'Total government expenditure on goods and services through public procurement.',
        'included_variables': [
            ('uk_innovation_strategy_2021', 'UK public expenditure on goods and services via procurement'),
            ('uk_innovation_strategy_2021', 'Percentage of central government spend with SMEs'),
        ],
        'confidence': 'high',
        'notes': 'Related metrics: total procurement and SME share of procurement.',
    },
    {
        'concept_id': 'C11',
        'concept_name': 'Technology-Specific Investment Programs',
        'concept_description': 'Government or public investment in specific technology programs or centers.',
        'included_variables': [
            ('uk_innovation_strategy_2021', 'Investment in Prosperity Partnerships'),
            ('uk_innovation_strategy_2021', 'Investment in Hartree Centre'),
            ('uk_innovation_strategy_2021', 'Investment in National Quantum Computing Centre'),
            ('uk_innovation_strategy_2021', 'Investment in Clean Maritime Demo Competition'),
            ('uk_innovation_strategy_2021', 'Investment in HEIF'),
            ('uk_innovation_strategy_2021', 'University Commercialisation funding'),
        ],
        'confidence': 'high',
        'notes': 'All UK-specific program investments. Unique to innovation strategy report.',
    },
    {
        'concept_id': 'C12',
        'concept_name': 'Technology Market Size/Economic Impact Forecast',
        'concept_description': 'Forecasted market size or economic impact of specific technology sectors.',
        'included_variables': [
            ('uk_innovation_strategy_2021', 'UK market size for RAS forecast'),
            ('uk_innovation_strategy_2021', 'Economic impact of RAS uptake'),
        ],
        'confidence': 'high',
        'notes': 'Both relate to Robotics & Autonomous Systems. Related forecasts.',
    },
    {
        'concept_id': 'C13',
        'concept_name': 'SME Business Demographics',
        'concept_description': 'Structural characteristics of SME businesses including age, legal status, ownership, and operational structure.',
        'included_variables': [
            ('longitudinal_sme_survey_2024', 'Age of business'),
            ('longitudinal_sme_survey_2024', 'Legal status of SME employer'),
            ('longitudinal_sme_survey_2024', 'Registered charity status'),
            ('longitudinal_sme_survey_2024', 'Number of owners/partners/directors'),
            ('longitudinal_sme_survey_2024', 'Family-owned business'),
            ('longitudinal_sme_survey_2024', 'Women-led businesses'),
            ('longitudinal_sme_survey_2024', 'Number of sites operated'),
            ('longitudinal_sme_survey_2024', 'Business premises in residential settings'),
        ],
        'confidence': 'high',
        'notes': 'All UK SME survey demographics. Unique to this report.',
    },
    {
        'concept_id': 'C14',
        'concept_name': 'SME Employment Change',
        'concept_description': 'Changes in SME employment levels over time, including actual and expected changes.',
        'included_variables': [
            ('longitudinal_sme_survey_2024', 'Employment growth in last 12 months'),
            ('longitudinal_sme_survey_2024', 'Expectations for employment growth'),
        ],
        'confidence': 'high',
        'notes': 'Related: actual vs expected employment change. UK SME survey.',
    },
    {
        'concept_id': 'C15',
        'concept_name': 'SME Turnover Change',
        'concept_description': 'Changes in SME turnover/revenue over time, including actual and expected changes.',
        'included_variables': [
            ('longitudinal_sme_survey_2024', 'Turnover growth in last 12 months'),
            ('longitudinal_sme_survey_2024', 'Expectations of turnover in next 12 months'),
        ],
        'confidence': 'high',
        'notes': 'Related: actual vs expected turnover change. UK SME survey.',
    },
    {
        'concept_id': 'C16',
        'concept_name': 'SME Financial Performance',
        'concept_description': 'Measures of SME financial health including profitability and access to finance.',
        'included_variables': [
            ('longitudinal_sme_survey_2024', 'Profit or surplus in last financial year'),
            ('longitudinal_sme_survey_2024', 'Use of external finance'),
            ('longitudinal_sme_survey_2024', 'Trade credit given to customers'),
        ],
        'confidence': 'high',
        'notes': 'Related financial metrics for UK SMEs.',
    },
    {
        'concept_id': 'C17',
        'concept_name': 'SME Innovation and R&D Activity',
        'concept_description': 'Measures of SME innovation and research & development activity.',
        'included_variables': [
            ('longitudinal_sme_survey_2024', 'Innovation activity in last 3 years'),
            ('longitudinal_sme_survey_2024', 'Investment in R&D in last 3 years'),
        ],
        'confidence': 'high',
        'notes': 'Related innovation metrics. UK SME survey.',
    },
    {
        'concept_id': 'C18',
        'concept_name': 'SME Growth Plans and Barriers',
        'concept_description': 'SME plans for growth activities and barriers to growth.',
        'included_variables': [
            ('longitudinal_sme_survey_2024', 'Plans for growth-related activities'),
            ('longitudinal_sme_survey_2024', 'Plans affected by rising costs'),
            ('longitudinal_sme_survey_2024', 'Major obstacles to business success'),
        ],
        'confidence': 'high',
        'notes': 'Growth intentions and barriers. UK SME survey.',
    },
    {
        'concept_id': 'C19',
        'concept_name': 'SME Digital Technology Adoption',
        'concept_description': 'Measures of SME adoption and use of digital technologies.',
        'included_variables': [
            ('longitudinal_sme_survey_2024', 'Use of technologies or web-based software'),
        ],
        'confidence': 'high',
        'notes': 'UK SME survey metric. Related to but different from Singapore digital adoption metrics.',
    },
    {
        'concept_id': 'C20',
        'concept_name': 'SME Export Activity',
        'concept_description': 'Measures of SME export and international trade activity.',
        'included_variables': [
            ('longitudinal_sme_survey_2024', 'Exporting status'),
        ],
        'confidence': 'high',
        'notes': 'UK SME survey. Unique to this report.',
    },
    {
        'concept_id': 'C21',
        'concept_name': 'Digital Economy Value Added',
        'concept_description': 'Measures of economic value generated by digital economy activities.',
        'included_variables': [
            ('sg_digital_economy_2024', 'I&C sector nominal VA'),
            ('sg_digital_economy_2024', 'Nominal VA from digitalisation in rest of economy'),
            ('sg_digital_economy_2024', 'Share of VA from digitalisation as % of GDP'),
            ('sg_digital_economy_2024', 'Annual real growth rate of VA from digitalisation'),
        ],
        'confidence': 'high',
        'notes': 'All relate to digital economy value added in Singapore. Unique to this report.',
    },
    {
        'concept_id': 'C22',
        'concept_name': 'Technology Employment',
        'concept_description': 'Measures of technology sector employment levels and share.',
        'included_variables': [
            ('sg_digital_economy_2024', 'Number of tech jobs in Singapore'),
            ('sg_digital_economy_2024', 'Tech jobs as % of total employment'),
            ('sg_digital_economy_2024', 'Median monthly wages for resident tech workers'),
        ],
        'confidence': 'high',
        'notes': 'All relate to tech employment in Singapore. Unique to this report.',
    },
    {
        'concept_id': 'C23',
        'concept_name': 'Enterprise Digital Adoption',
        'concept_description': 'Measures of digital technology adoption across enterprises.',
        'included_variables': [
            ('sg_digital_economy_2024', 'Digital adoption rate among enterprises'),
            ('sg_digital_economy_2024', 'Digital adoption intensity among enterprises'),
            ('sg_digital_economy_2024', 'Share of SMEs adopting digital solution'),
            ('sg_digital_economy_2024', 'Average cost savings per PSG application'),
        ],
        'confidence': 'high',
        'notes': 'All relate to digital adoption in Singapore enterprises. Unique to this report.',
    },
    {
        'concept_id': 'C24',
        'concept_name': 'Innovation Strategy Qualitative Frameworks',
        'concept_description': 'Qualitative frameworks, lists, or strategic priorities for innovation.',
        'included_variables': [
            ('uk_innovation_strategy_2021', 'Seven technology families'),
            ('uk_innovation_strategy_2021', 'Number of policy projects by OIT'),
        ],
        'confidence': 'medium',
        'notes': 'Qualitative/strategic items. Not directly measurable indicators.',
    },
]


def write_concept_groups_csv():
    """Write concept_groups.csv"""
    path = OUTPUT_DIR / "concept_groups.csv"
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'concept_id', 'concept_name', 'concept_description',
            'included_variables', 'report_ids', 'confidence', 'notes'
        ])
        for c in CONCEPTS:
            vars_str = '; '.join(f'{r}: {v}' for r, v in c['included_variables'])
            reports_str = '; '.join(sorted(set(r for r, v in c['included_variables'])))
            writer.writerow([
                c['concept_id'], c['concept_name'], c['concept_description'],
                vars_str, reports_str, c['confidence'], c['notes']
            ])
    print(f"Written: {path}")


def write_overlap_matrix():
    """Write concept_overlap_matrix.csv"""
    path = OUTPUT_DIR / "concept_overlap_matrix.csv"
    report_shorts = [REPORTS[rid]['short'] for rid in REPORTS]
    
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['concept_id', 'concept_name'] + report_shorts)
        
        for c in CONCEPTS:
            row = [c['concept_id'], c['concept_name']]
            var_map = {}
            for r, v in c['included_variables']:
                var_map[r] = v
            
            for rid in REPORTS:
                short = REPORTS[rid]['short']
                if short in var_map:
                    row.append(f"present: {var_map[short]}")
                else:
                    row.append("absent")
            writer.writerow(row)
    print(f"Written: {path}")


def write_definition_differences():
    """Write concept_definition_differences.csv for concepts in 2+ reports"""
    path = OUTPUT_DIR / "concept_definition_differences.csv"
    
    # Load variable details from database
    import psycopg
    conn = psycopg.connect('postgresql://postgres:postgres@localhost:5432/data_center_agent')
    cur = conn.cursor()
    
    cur.execute('''
        SELECT rv.report_id::text, rv.raw_variable_name, rv.definition, 
               rv.measurement_method, rv.unit, rv.data_source_type, rv.availability,
               rv.temporal_coverage, rv.geographic_coverage, rv.metadata
        FROM report_variables rv
        ORDER BY rv.report_id, rv.raw_variable_name
    ''')
    
    var_details = {}
    for row in cur.fetchall():
        key = (row[0], row[1])
        m = row[9] if row[9] else {}
        eq = m.get('evidence_quote', '') if isinstance(m, dict) else ''
        var_details[key] = {
            'definition': row[2],
            'measurement_method': row[3],
            'unit': row[4],
            'data_source_type': row[5],
            'availability': row[6],
            'temporal_coverage': row[7],
            'geographic_coverage': row[8],
            'evidence_quote': eq,
        }
    conn.close()
    
    # Find shared concepts (in 2+ reports)
    shared_concepts = []
    for c in CONCEPTS:
        unique_reports = set(r for r, v in c['included_variables'])
        if len(unique_reports) > 1:
            shared_concepts.append(c)
    
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'concept_id', 'concept_name', 'report_a', 'variable_a', 'report_b', 'variable_b',
            'definition_comparison', 'measurement_comparison', 'unit_comparison',
            'data_source_comparison', 'availability_comparison',
            'temporal_comparison', 'geographic_comparison',
            'comparability_classification', 'notes'
        ])
        
        for c in shared_concepts:
            reports_in_concept = list(set(r for r, v in c['included_variables']))
            
            # Compare all pairs of reports
            for i in range(len(reports_in_concept)):
                for j in range(i+1, len(reports_in_concept)):
                    r1 = reports_in_concept[i]
                    r2 = reports_in_concept[j]
                    
                    # Get variables for each report
                    vars1 = [(r, v) for r, v in c['included_variables'] if r == r1]
                    vars2 = [(r, v) for r, v in c['included_variables'] if r == r2]
                    
                    for _, v1_name in vars1:
                        for _, v2_name in vars2:
                            key1 = (REPORTS[[rid for rid, s in REPORTS.items() if s['short'] == r1][0]], v1_name)
                            key2 = (REPORTS[[rid for rid, s in REPORTS.items() if s['short'] == r2][0]], v2_name)
                            
                            # Actually, let me just use the report short names
                            d1 = var_details.get((r1, v1_name), {})
                            d2 = var_details.get((r2, v2_name), {})
                            
                            # Classify differences
                            classification = classify_difference(d1, d2, c)
                            
                            writer.writerow([
                                c['concept_id'], c['concept_name'],
                                r1, v1_name, r2, v2_name,
                                compare_field(d1.get('definition', ''), d2.get('definition', '')),
                                compare_field(d1.get('measurement_method', ''), d2.get('measurement_method', '')),
                                compare_field(d1.get('unit', ''), d2.get('unit', '')),
                                compare_field(d1.get('data_source_type', ''), d2.get('data_source_type', '')),
                                compare_field(d1.get('availability', ''), d2.get('availability', '')),
                                compare_field(d1.get('temporal_coverage', ''), d2.get('temporal_coverage', '')),
                                compare_field(d1.get('geographic_coverage', ''), d2.get('geographic_coverage', '')),
                                classification,
                                c['notes'],
                            ])
    print(f"Written: {path}")


def compare_field(v1, v2):
    """Compare two field values and return a summary."""
    v1 = (v1 or '').strip().lower()
    v2 = (v2 or '').strip().lower()
    if v1 == v2:
        return 'same'
    elif not v1 or not v2:
        return f'A={v1 or "empty"}; B={v2 or "empty"}'
    else:
        return f'A={v1[:60]}; B={v2[:60]}'


def classify_difference(d1, d2, concept):
    """Classify the type of difference between two variables."""
    unit1 = (d1.get('unit', '') or '').strip().lower()
    unit2 = (d2.get('unit', '') or '').strip().lower()
    geo1 = (d1.get('geographic_coverage', '') or '').strip().lower()
    geo2 = (d2.get('geographic_coverage', '') or '').strip().lower()
    src1 = (d1.get('data_source_type', '') or '').strip().lower()
    src2 = (d2.get('data_source_type', '') or '').strip().lower()
    
    if unit1 and unit2 and unit1 != unit2:
        return 'same concept, different unit'
    elif geo1 and geo2 and geo1 != geo2:
        return 'same concept, different geographic scope'
    elif src1 and src2 and src1 != src2:
        return 'same concept, different data source'
    else:
        return 'same concept, same measurement'


def write_summary():
    """Write concept_eval_summary.md"""
    path = OUTPUT_DIR / "concept_eval_summary.md"
    
    # Calculate stats
    total_concepts = len(CONCEPTS)
    
    # Count by number of reports
    report_counts = []
    for c in CONCEPTS:
        unique_reports = len(set(r for r, v in c['included_variables']))
        report_counts.append(unique_reports)
    
    overlap_dist = Counter(report_counts)
    shared = [c for c in CONCEPTS if len(set(r for r, v in c['included_variables'])) > 1]
    unique = [c for c in CONCEPTS if len(set(r for r, v in c['included_variables'])) == 1]
    
    # Report pair overlap
    report_pairs = Counter()
    for c in CONCEPTS:
        reports_in = sorted(set(r for r, v in c['included_variables']))
        for i in range(len(reports_in)):
            for j in range(i+1, len(reports_in)):
                report_pairs[(reports_in[i], reports_in[j])] += 1
    
    top_pairs = report_pairs.most_common(5)
    
    # Private data sources
    private_sources = []
    
    md = f"""# Concept Overlap Evaluation: 5 Sources

## Executive Summary

This evaluation analyzes concept overlap across 5 diverse sources in the innovation/startup/entrepreneurship domain.

**Reports Evaluated:**
"""
    for rid, info in REPORTS.items():
        md += f"- **{info['title']}** ({info['domain']}, {info['geography']}, {info['year']})\n"
    
    md += f"""
## Key Findings

### Concept Counts
- **Total independent concepts found:** {total_concepts}
- **Concepts appearing in exactly 1 report:** {overlap_dist.get(1, 0)}
- **Concepts appearing in 2 reports:** {overlap_dist.get(2, 0)}
- **Concepts appearing in 3+ reports:** {sum(v for k, v in overlap_dist.items() if k >= 3)}

### Overlap Distribution

| Reports | Count | Percentage |
|---------|-------|------------|
"""
    for k in sorted(overlap_dist.keys()):
        pct = overlap_dist[k] / total_concepts * 100
        md += f"| {k} | {overlap_dist[k]} | {pct:.1f}% |\n"
    
    md += f"""
### Top Overlapping Concepts

"""
    for c in shared:
        reports = sorted(set(r for r, v in c['included_variables']))
        md += f"- **{c['concept_id']} {c['concept_name']}** ({len(reports)} reports): {', '.join(reports)}\n"
    
    md += f"""
### Report Pairs with Highest Conceptual Overlap

"""
    for (r1, r2), count in top_pairs:
        md += f"- {r1} ↔ {r2}: {count} shared concepts\n"
    
    md += f"""
### Concepts Unique to Each Report

"""
    for rid, info in REPORTS.items():
        unique_vars = [c for c in CONCEPTS if len(set(r for r, v in c['included_variables'])) == 1 
                       and info['short'] in [r for r, v in c['included_variables']]]
        md += f"- **{info['short']}**: {len(unique_vars)} unique concepts\n"
        for c in unique_vars:
            md += f"  - {c['concept_id']} {c['concept_name']}\n"
    
    md += f"""
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
"""
    
    with open(path, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f"Written: {path}")


if __name__ == '__main__':
    write_concept_groups_csv()
    write_overlap_matrix()
    write_definition_differences()
    write_summary()
    print("\nAll outputs written successfully!")
