#!/usr/bin/env python3
"""
VC/Funding Cluster: Concept Overlap Evaluation
5 reports: SG Venture 2022, SE US 2025, SG Venture 2024, UK Equity Tracker 2024, UK Equity Tracker 2025
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from collections import defaultdict
import os, json, re

OUT = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. LOAD ALL CODEBOOKS
# ============================================================

# Load existing codebooks (from the original 5-source eval)
old_cb = pd.read_csv("/home/ubuntu/Venture-Metrics-db/concept_eval_5_sources/per_report_codebooks.csv")
old_sg = old_cb[old_cb['report_title'].str.contains('VENTURE FUNDING', case=False, na=False)].copy()
old_us = old_cb[old_cb['report_title'].str.contains('Startups in the Southeast', case=False, na=False)].copy()

# Load new codebooks
new_sg = pd.read_csv(f"{OUT}/codebook_sg_venture_2024.csv")
new_uk25 = pd.read_csv(f"{OUT}/codebook_uk_equity_tracker_2025.csv")
new_uk24 = pd.read_csv(f"{OUT}/codebook_uk_equity_tracker_2024.csv")

# Standardize column names for old codebooks
def standardize_cb(df, source_name, cols_needed):
    """Normalize old codebook format to match new extraction format."""
    rows = []
    for _, row in df.iterrows():
        rows.append({
            'variable_name': row.get('raw_variable_name', row.get('variable_name', '')),
            'definition': row.get('definition', ''),
            'measurement_method': row.get('measurement_method', ''),
            'unit': row.get('unit', ''),
            'data_source_type': row.get('data_source_type', ''),
            'geographic_coverage': row.get('geographic_coverage', ''),
            'temporal_coverage': row.get('temporal_coverage', ''),
            'confidence_score': row.get('confidence_score', 0.9),
        })
    return pd.DataFrame(rows)

old_sg_std = standardize_cb(old_sg, 'sg_venture_2022', None)
old_us_std = standardize_cb(old_us, 'se_us_startups_2025', None)

# Ensure all codebooks have same columns
all_cbs = {
    'sg_venture_2022': old_sg_std,
    'se_us_startups_2025': old_us_std,
    'sg_venture_2024': new_sg,
    'uk_equity_tracker_2024': new_uk24,
    'uk_equity_tracker_2025': new_uk25,
}

print("=== CODEBOOK SIZES ===")
for name, cb in all_cbs.items():
    print(f"  {name}: {len(cb)} variables")

# ============================================================
# 2. NORMALIZE VARIABLES TO CONCEPTS
# ============================================================

# Define concept normalization rules for VC/funding domain
concept_rules = {
    # Core deal metrics
    'deal_volume': {
        'name': 'Deal Volume / Deal Count',
        'match_patterns': [r'deal.{0,5}volume', r'deal.{0,5}count', r'number.{0,10}deal', r'vc.{0,5}deal', r'equity.{0,5}deal.{0,5}count'],
    },
    'deal_value': {
        'name': 'Total Deal Value / Investment Value',
        'match_patterns': [r'deal.{0,5}value', r'total.{0,10}invest', r'capital.{0,5}deploy', r'equity.{0,5}invest', r'vc.{0,5}invest', r'investment.{0,5}value'],
    },
    'avg_deal_size': {
        'name': 'Average Deal Size',
        'match_patterns': [r'avg.{0,5}deal', r'average.{0,5}deal', r'check.{0,5}size', r'mean.{0,5}deal'],
    },
    'median_deal_size': {
        'name': 'Median Deal Size',
        'match_patterns': [r'median.{0,5}deal', r'median.{0,5}check'],
    },
    # Stage breakdowns
    'stage_breakdown': {
        'name': 'Deal Distribution by Stage',
        'match_patterns': [r'stage.{0,5}break', r'stage.{0,5}distribut', r'seed.{0,5}series', r'early.{0,5}stage', r'venture.{0,5}stage', r'growth.{0,5}stage', r'stage.{0,5}cohort', r'stage.{0,5}share'],
    },
    # Sector breakdowns
    'sector_breakdown': {
        'name': 'Deal Distribution by Sector',
        'match_patterns': [r'sector.{0,5}break', r'sector.{0,5}distribut', r'by.{0,5}sector', r'industry.{0,5}break', r'tech.{0,5}vs', r'deep.{0,5}tech', r'fintech', r'healthcare.{0,5}sector'],
    },
    # Regional/geographic breakdowns
    'regional_breakdown': {
        'name': 'Regional Distribution',
        'match_patterns': [r'region', r'geograph', r'london', r'south.{0,5}east', r'local.{0,5}authority', r'regional.{0,5}distrib', r'by.{0,5}region'],
    },
    # International comparison
    'intl_comparison': {
        'name': 'International Comparison',
        'match_patterns': [r'international', r'global.{0,5}compar', r'uk.{0,5}vs.{0,5}us', r'asean', r'global.{0,5}share', r'global.{0,5}rank', r'worldwide', r'country.{0,5}compar'],
    },
    # Valuation metrics
    'pre_money_valuation': {
        'name': 'Pre-money Valuation',
        'match_patterns': [r'pre.{0,5}money', r'valuation.{0,5}pre', r'pre.{0,5}money.{0,5}valuat'],
    },
    'post_money_valuation': {
        'name': 'Post-money Valuation',
        'match_patterns': [r'post.{0,5}money', r'valuation.{0,5}post'],
    },
    # Ecosystem size
    'ecosystem_size': {
        'name': 'Ecosystem Size / Number of Companies',
        'match_patterns': [r'number.{0,10}compan', r'number.{0,10}startup', r'ecosystem.{0,5}size', r'number.{0,10}vc.{0,5}firm', r'number.{0,10}accelerat'],
    },
    # YoY growth / change
    'yoy_change': {
        'name': 'Year-on-Year Change / Growth Rate',
        'match_patterns': [r'year.{0,5}on.{0,5}year', r'yoy', r'growth.{0,5}rate', r'change.{0,5}from', r'increase.{0,5}from', r'vs.{0,5}prior', r'vs.{0,5}last'],
    },
    # IPO / exit activity
    'ipo_activity': {
        'name': 'IPO / Exit Activity',
        'match_patterns': [r'ipo', r'exit.{0,5}activ', r'public.{0,5}list', r'm.{0,5}a', r'acquisition'],
    },
    # Gender/diversity
    'gender_diversity': {
        'name': 'Gender Diversity in Founding Teams',
        'match_patterns': [r'gender', r'female.{0,5}found', r'women.{0,5}found', r'diversity', r'investing.{0,5}women'],
    },
    # Government/policy support
    'govt_support': {
        'name': 'Government Support / Policy Programs',
        'match_patterns': [r'govern', r'policy', r'public.{0,5}fund', r'eis', r'seis', r'tax.{0,5}relief', r'grant', r'programme', r'startup.{0,5}sg'],
    },
    # Quarterly/periodic data
    'quarterly_data': {
        'name': 'Quarterly Breakdown',
        'match_patterns': [r'q[1-4]', r'quarter', r'monthly', r'nine.{0,3}month', r'9.{0,3}month'],
    },
    # Spinout/university
    'spinout_activity': {
        'name': 'University Spinout Activity',
        'match_patterns': [r'spinout', r'university.{0,5}spin', r'commercialis', r'academic.{0,5}entrepreneur'],
    },
    # Angel/informal investment
    'angel_investment': {
        'name': 'Business Angel / Informal Investment',
        'match_patterns': [r'angel', r'informal.{0,5}invest', r'co.{0,5}invest'],
    },
    # Sector-specific: AI
    'ai_sector': {
        'name': 'AI Sector Metrics',
        'match_patterns': [r'\bai\b', r'artificial.{0,5}intellig', r'machine.{0,5}learn'],
    },
    # Sector-specific: cleantech/green
    'cleantech_sector': {
        'name': 'Cleantech / Green Tech Metrics',
        'match_patterns': [r'clean.{0,5}tech', r'green.{0,5}tech', r'climate', r'sustainab'],
    },
    # Real vs nominal terms
    'real_nominal': {
        'name': 'Real vs Nominal Adjustment',
        'match_patterns': [r'real.{0,5}term', r'nominal.{0,5}term', r'gdp.{0,5}deflat', r'inflation.{0,5}adjust', r'real.{0,5}gdp'],
    },
}


def match_variable_to_concept(var_name, definition, rules):
    """Match a variable to its concept group based on name and definition patterns."""
    text = f"{var_name} {definition}".lower()
    matched = []
    for concept_id, rule in rules.items():
        for pattern in rule['match_patterns']:
            if re.search(pattern, text):
                matched.append(concept_id)
                break
    if len(matched) == 1:
        return matched[0]
    elif len(matched) > 1:
        # Prefer more specific matches
        return matched[0]  # Take first (most specific) match
    return None  # No match


# ============================================================
# 3. BUILD CONCEPT-BY-REPORT MATRIX
# ============================================================

report_ids = list(all_cbs.keys())
report_labels = {
    'sg_venture_2022': 'SG Venture\nFunding 2022',
    'se_us_startups_2025': 'SE US\nStartups 2025',
    'sg_venture_2024': 'SG Venture\nFunding 2024',
    'uk_equity_tracker_2024': 'UK Equity\nTracker 2024',
    'uk_equity_tracker_2025': 'UK Equity\nTracker 2025',
}

# Map variables to concepts
concept_presence = {}  # concept_id -> {report_id: [list of variables]}
variable_to_concept = {}  # (report_id, var_name) -> concept_id

for report_id, cb in all_cbs.items():
    for _, row in cb.iterrows():
        var_name = str(row['variable_name'])
        definition = str(row.get('definition', ''))
        concept_id = match_variable_to_concept(var_name, definition, concept_rules)
        if concept_id:
            variable_to_concept[(report_id, var_name)] = concept_id
            if concept_id not in concept_presence:
                concept_presence[concept_id] = defaultdict(list)
            concept_presence[concept_id][report_id].append({
                'variable_name': var_name,
                'definition': definition[:200],
                'unit': str(row.get('unit', '')),
            })

# Filter: only keep concepts present in 2+ reports
shared_concepts = {k: v for k, v in concept_presence.items() if len(v) >= 2}
all_concepts = {k: v for k, v in concept_presence.items()}

print(f"\n=== CONCEPT MAPPING RESULTS ===")
print(f"Total variables mapped to concepts: {sum(len(v) for r in all_cbs.values() for v in [variable_to_concept.get((rid, vn), None) for rid, cb in all_cbs.items() for vn in cb['variable_name']]) if False else len(variable_to_concept)}")
print(f"Total concepts found: {len(all_concepts)}")
print(f"Concepts in 2+ reports: {len(shared_concepts)}")
print(f"Concepts in 3+ reports: {sum(1 for v in shared_concepts.values() if len(v) >= 3)}")

# ============================================================
# 4. BUILD OVERLAP MATRIX
# ============================================================

# Create binary matrix
matrix_data = []
for concept_id in sorted(all_concepts.keys()):
    row = {'concept_id': concept_id, 'concept_name': concept_rules[concept_id]['name']}
    for report_id in report_ids:
        if report_id in all_concepts[concept_id]:
            vars_found = all_concepts[concept_id][report_id]
            row[report_id] = f"present: {vars_found[0]['variable_name']}"
        else:
            row[report_id] = 'absent'
    matrix_data.append(row)

overlap_df = pd.DataFrame(matrix_data)
overlap_df.to_csv(f"{OUT}/concept_overlap_matrix.csv", index=False)

# Create concept groups CSV
groups_data = []
for concept_id in sorted(all_concepts.keys()):
    reports = list(all_concepts[concept_id].keys())
    all_vars = []
    for r in reports:
        for v in all_concepts[concept_id][r]:
            all_vars.append(f"{r}: {v['variable_name']}")
    groups_data.append({
        'concept_id': concept_id,
        'concept_name': concept_rules[concept_id]['name'],
        'concept_description': f"VC/funding metric: {concept_rules[concept_id]['name']}",
        'included_variables': '; '.join(all_vars),
        'report_ids': '; '.join(reports),
        'confidence': 'high' if len(reports) >= 2 else 'medium',
    })

groups_df = pd.DataFrame(groups_data)
groups_df.to_csv(f"{OUT}/concept_groups.csv", index=False)

# ============================================================
# 5. ANALYZE DEFINITION DIFFERENCES
# ============================================================

diff_data = []
for concept_id in sorted(shared_concepts.keys()):
    reports = shared_concepts[concept_id]
    for r1 in sorted(reports.keys()):
        for r2 in sorted(reports.keys()):
            if r1 < r2:
                for v1 in reports[r1]:
                    for v2 in reports[r2]:
                        # Compare definitions
                        def1 = v1['definition'][:200]
                        def2 = v2['definition'][:200]
                        unit1 = v1['unit']
                        unit2 = v2['unit']
                        
                        # Classify differences
                        diffs = []
                        if def1.lower() != def2.lower():
                            diffs.append('definition_text')
                        if unit1.lower() != unit2.lower():
                            diffs.append('unit')
                        if not diffs:
                            diffs.append('identical')
                        
                        diff_data.append({
                            'concept_id': concept_id,
                            'concept_name': concept_rules[concept_id]['name'],
                            'report_1': r1,
                            'variable_1': v1['variable_name'],
                            'definition_1': def1,
                            'unit_1': unit1,
                            'report_2': r2,
                            'variable_2': v2['variable_name'],
                            'definition_2': def2,
                            'unit_2': unit2,
                            'differences': '; '.join(diffs),
                        })

diff_df = pd.DataFrame(diff_data)
diff_df.to_csv(f"{OUT}/concept_definition_differences.csv", index=False)

# ============================================================
# 6. GENERATE SUMMARY STATS
# ============================================================

binary_matrix = {}
for concept_id in sorted(all_concepts.keys()):
    binary_matrix[concept_id] = {}
    for report_id in report_ids:
        binary_matrix[concept_id][report_id] = 1 if report_id in all_concepts[concept_id] else 0

binary_df = pd.DataFrame(binary_matrix).T
binary_df.columns = report_ids

# Frequency distribution
freq = binary_df.sum(axis=1).astype(int)
freq_dist = freq.value_counts().sort_index()

print(f"\n=== OVERLAP DISTRIBUTION ===")
for n_reports, count in freq_dist.items():
    print(f"  {n_reports} reports: {count} concepts")

# Report pairs with highest overlap
print(f"\n=== TOP OVERLAP PAIRS ===")
for i, r1 in enumerate(report_ids):
    for r2 in report_ids[i+1:]:
        shared = sum(1 for c in all_concepts if r1 in all_concepts[c] and r2 in all_concepts[c])
        if shared > 0:
            print(f"  {r1} ↔ {r2}: {shared} shared concepts")

# ============================================================
# 7. GENERATE VISUALIZATIONS
# ============================================================

short_labels = {k: v.replace('\n', ' ') for k, v in report_labels.items()}

# --- 7a. HEATMAP ---
fig, ax = plt.subplots(figsize=(14, 10))
labels = report_ids
data = binary_df[labels].values
concept_labels = [concept_rules[cid]['name'] for cid in binary_df.index]

cmap = matplotlib.colors.ListedColormap(['#f0f0f0', '#1565C0'])
bounds = [-0.5, 0.5, 1.5]
norm = matplotlib.colors.BoundaryNorm(bounds, cmap.N)

im = ax.imshow(data, cmap=cmap, norm=norm, aspect='auto')
ax.set_xticks(range(len(labels)))
ax.set_xticklabels([short_labels[l] for l in labels], fontsize=9, ha='center')
ax.set_yticks(range(len(concept_labels)))
ax.set_yticklabels(concept_labels, fontsize=8)

for i in range(len(concept_labels)):
    for j in range(len(labels)):
        val = data[i, j]
        color = 'white' if val == 1 else '#999'
        symbol = '●' if val == 1 else '—'
        ax.text(j, i, symbol, ha='center', va='center', fontsize=10, color=color, fontweight='bold')

ax.set_title('VC/Funding Concept Presence Across 5 Reports\n(● = Present, — = Absent)', fontsize=14, fontweight='bold', pad=15)
ax.spines[:].set_visible(False)
ax.tick_params(top=False, bottom=False, left=False, right=False)
legend_elements = [
    mpatches.Patch(facecolor='#1565C0', edgecolor='gray', label='Present'),
    mpatches.Patch(facecolor='#f0f0f0', edgecolor='gray', label='Absent'),
]
ax.legend(handles=legend_elements, loc='lower right', fontsize=10)
plt.tight_layout()
plt.savefig(f"{OUT}/viz_heatmap.png", dpi=150, bbox_inches='tight', facecolor='white')
plt.close()
print("✓ viz_heatmap.png")

# --- 7b. CONCEPTS PER REPORT ---
fig, ax = plt.subplots(figsize=(10, 5))
counts = [int(binary_df[col].sum()) for col in labels]
colors = ['#0D47A1', '#1565C0', '#1976D2', '#2196F3', '#42A5F5']
bars = ax.barh([short_labels[l] for l in labels], counts, color=colors, edgecolor='white', height=0.6)
for bar, count in zip(bars, counts):
    ax.text(bar.get_width() + 0.2, bar.get_y() + bar.get_height()/2, str(int(count)),
            va='center', fontsize=11, fontweight='bold', color='#333')
ax.set_xlabel('Number of Concepts', fontsize=11)
ax.set_title('VC/Funding Concept Count by Report', fontsize=14, fontweight='bold')
ax.set_xlim(0, max(counts) + 2)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
plt.tight_layout()
plt.savefig(f"{OUT}/viz_concepts_per_report.png", dpi=150, bbox_inches='tight', facecolor='white')
plt.close()
print("✓ viz_concepts_per_report.png")

# --- 7c. OVERLAP DISTRIBUTION ---
fig, ax = plt.subplots(figsize=(8, 5))
ax.bar(freq_dist.index.astype(str), freq_dist.values, color='#FF6F00', edgecolor='white', width=0.5)
for x, y in zip(freq_dist.index.astype(str), freq_dist.values):
    ax.text(int(x)-1, y + 0.3, str(y), ha='center', fontsize=11, fontweight='bold', color='#333')
ax.set_xlabel('Number of Reports Containing Concept', fontsize=11)
ax.set_ylabel('Number of Concepts', fontsize=11)
ax.set_title('VC/Funding Concept Overlap Distribution', fontsize=14, fontweight='bold')
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
plt.tight_layout()
plt.savefig(f"{OUT}/viz_overlap_distribution.png", dpi=150, bbox_inches='tight', facecolor='white')
plt.close()
print("✓ viz_overlap_distribution.png")

# --- 7d. PAIR OVERLAP MATRIX ---
fig, ax = plt.subplots(figsize=(8, 7))
n = len(labels)
matrix = np.zeros((n, n), dtype=int)
for i in range(n):
    for j in range(n):
        if i == j:
            matrix[i][j] = int(binary_df[labels[i]].sum())
        else:
            shared = sum(1 for c in binary_df.index if binary_df.loc[c, labels[i]] == 1 and binary_df.loc[c, labels[j]] == 1)
            matrix[i][j] = shared

im = ax.imshow(matrix, cmap='YlOrRd', aspect='auto')
short = [short_labels[l] for l in labels]
ax.set_xticks(range(n))
ax.set_xticklabels(short, rotation=30, ha='right', fontsize=9)
ax.set_yticks(range(n))
ax.set_yticklabels(short, fontsize=9)
for i in range(n):
    for j in range(n):
        val = matrix[i][j]
        color = 'white' if val > 3 else '#333'
        ax.text(j, i, str(val), ha='center', va='center', fontsize=12, fontweight='bold', color=color)
ax.set_title('VC/Funding Report Pair Overlap Matrix', fontsize=14, fontweight='bold', pad=15)
plt.colorbar(im, ax=ax, shrink=0.7, label='Shared Concepts')
ax.spines[:].set_visible(False)
ax.tick_params(top=False, bottom=False, left=False, right=False)
plt.tight_layout()
plt.savefig(f"{OUT}/viz_pair_overlap_matrix.png", dpi=150, bbox_inches='tight', facecolor='white')
plt.close()
print("✓ viz_pair_overlap_matrix.png")

# --- 7e. DEFINITION DIVERGENCE ---
if len(diff_df) > 0:
    # Count diff types per concept
    concept_diffs = diff_df.groupby('concept_id')['differences'].apply(lambda x: sum(1 for v in x if 'unit' in v)).reset_index()
    concept_diffs.columns = ['concept_id', 'unit_mismatch_count']
    
    # Also count definition text differences
    def_mismatches = diff_df.groupby('concept_id')['differences'].apply(lambda x: sum(1 for v in x if 'definition_text' in v)).reset_index()
    def_mismatches.columns = ['concept_id', 'def_mismatch_count']
    concept_diffs = concept_diffs.merge(def_mismatches, on='concept_id', how='left')
    concept_diffs['def_mismatch_count'] = concept_diffs['def_mismatch_count'].fillna(0).astype(int)
    
    fig, ax = plt.subplots(figsize=(10, 6))
    x = range(len(concept_diffs))
    width = 0.35
    concept_names = [concept_rules.get(cid, {}).get('name', cid)[:20] for cid in concept_diffs['concept_id']]
    
    # Only show concepts with differences
    mask = (concept_diffs['unit_mismatch_count'] > 0) | (concept_diffs['def_mismatch_count'] > 0)
    concept_diffs_filtered = concept_diffs[mask]
    concept_names_filtered = [concept_rules.get(cid, {}).get('name', cid)[:25] for cid in concept_diffs_filtered['concept_id']]
    
    if len(concept_diffs_filtered) > 0:
        x = range(len(concept_diffs_filtered))
        bars1 = ax.bar([i - width/2 for i in x], concept_diffs_filtered['def_mismatch_count'].values, width, label='Definition Text Differences', color='#EF5350')
        bars2 = ax.bar([i + width/2 for i in x], concept_diffs_filtered['unit_mismatch_count'].values, width, label='Unit Differences', color='#42A5F5')
        ax.set_xticks(list(x))
        ax.set_xticklabels(concept_names_filtered, rotation=45, ha='right', fontsize=9)
        ax.set_ylabel('Number of Pairwise Differences', fontsize=11)
        ax.set_title('Definition Divergence Across Reports\n(Pairwise comparison of shared concepts)', fontsize=13, fontweight='bold')
        ax.legend(fontsize=10)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        plt.tight_layout()
        plt.savefig(f"{OUT}/viz_definition_divergence.png", dpi=150, bbox_inches='tight', facecolor='white')
        plt.close()
        print("✓ viz_definition_divergence.png")

# --- 7f. GEOGRAPHIC FOCUS ---
fig, ax = plt.subplots(figsize=(10, 6))
geo_groups = {
    'Singapore': ['sg_venture_2022', 'sg_venture_2024'],
    'Southeast US': ['se_us_startups_2025'],
    'United Kingdom': ['uk_equity_tracker_2024', 'uk_equity_tracker_2025'],
}
geo_colors = {'Singapore': '#D32F2F', 'Southeast US': '#1565C0', 'United Kingdom': '#2E7D32'}

# Count unique and shared concepts per geography
geo_unique = {}
geo_shared = {}
for geo, reps in geo_groups.items():
    unique = 0
    shared_with_other = 0
    for cid in all_concepts:
        reports_with = [r for r in reps if r in all_concepts[cid]]
        other_reports = [r for r in report_ids if r not in reps]
        if len(reports_with) > 0:
            has_other = any(r in all_concepts[cid] for r in other_reports)
            if has_other:
                shared_with_other += 1
            else:
                unique += 1
    geo_unique[geo] = unique
    geo_shared[geo] = shared_with_other

x = range(len(geo_groups))
geos = list(geo_groups.keys())
bars1 = ax.bar([i - 0.2 for i in x], [geo_unique[g] for g in geos], 0.4, label='Geo-Unique Concepts', color=[geo_colors[g] for g in geos], alpha=0.8)
bars2 = ax.bar([i + 0.2 for i in x], [geo_shared[g] for g in geos], 0.4, label='Shared with Other Geos', color=[geo_colors[g] for g in geos], alpha=0.4, edgecolor='gray')

for bar in bars1:
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.2, str(int(bar.get_height())),
            ha='center', fontsize=10, fontweight='bold')
for bar in bars2:
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.2, str(int(bar.get_height())),
            ha='center', fontsize=10, fontweight='bold')

ax.set_xticks(list(x))
ax.set_xticklabels(geos, fontsize=11)
ax.set_ylabel('Number of Concepts', fontsize=11)
ax.set_title('Concept Coverage by Geography\n(Unique vs Cross-Geography Shared)', fontsize=14, fontweight='bold')
ax.legend(fontsize=10)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
plt.tight_layout()
plt.savefig(f"{OUT}/viz_geographic_coverage.png", dpi=150, bbox_inches='tight', facecolor='white')
plt.close()
print("✓ viz_geographic_coverage.png")

# ============================================================
# 8. WRITE SUMMARY REPORT
# ============================================================

summary_lines = [
    "# VC/Funding Cluster: Concept Overlap Evaluation",
    "",
    "## Reports Evaluated",
    "",
    "| # | Report | Geography | Variables |",
    "|---|--------|-----------|-----------|",
]
for i, (rid, cb) in enumerate(all_cbs.items(), 1):
    summary_lines.append(f"| {i} | {report_labels[rid].replace(chr(10), ' ')} | {rid.split('_')[0].upper()} | {len(cb)} |")

summary_lines += [
    "",
    "## Key Findings",
    "",
    f"- **Total independent concepts found:** {len(all_concepts)}",
    f"- **Concepts appearing in exactly 1 report:** {sum(1 for v in all_concepts.values() if len(v) == 1)}",
    f"- **Concepts appearing in 2+ reports:** {len(shared_concepts)}",
    f"- **Concepts appearing in 3+ reports:** {sum(1 for v in shared_concepts.values() if len(v) >= 3)}",
    "",
    "### Overlap Distribution",
    "",
    "| Reports | Count | Percentage |",
    "|---------|-------|------------|",
]

total_concepts = len(all_concepts)
for n_reports, count in freq_dist.items():
    pct = count / total_concepts * 100
    summary_lines.append(f"| {n_reports} | {count} | {pct:.1f}% |")

summary_lines += [
    "",
    "### Top Overlapping Concepts",
    "",
]

for concept_id in sorted(shared_concepts.keys(), key=lambda x: -len(shared_concepts[x])):
    reports = shared_concepts[concept_id]
    report_names = ', '.join(sorted(reports.keys()))
    summary_lines.append(f"- **{concept_rules[concept_id]['name']}** ({len(reports)} reports): {report_names}")

summary_lines += [
    "",
    "### Report Pairs with Highest Conceptual Overlap",
    "",
]

for i, r1 in enumerate(report_ids):
    for r2 in report_ids[i+1:]:
        shared_count = sum(1 for c in all_concepts if r1 in all_concepts[c] and r2 in all_concepts[c])
        if shared_count > 0:
            summary_lines.append(f"- {short_labels[r1]} ↔ {short_labels[r2]}: {shared_count} shared concepts")

summary_lines += [
    "",
    "## Visualizations",
    "",
    "| Chart | File | Description |",
    "|-------|------|-------------|",
    "| Concept Heatmap | `viz_heatmap.png` | Full presence/absence matrix |",
    "| Concepts per Report | `viz_concepts_per_report.png` | Concept count by report |",
    "| Overlap Distribution | `viz_overlap_distribution.png` | How many reports share each concept |",
    "| Pair Overlap Matrix | `viz_pair_overlap_matrix.png` | Shared concepts between report pairs |",
    "| Definition Divergence | `viz_definition_divergence.png` | Definition vs unit differences for shared concepts |",
    "| Geographic Coverage | `viz_geographic_coverage.png` | Unique vs cross-geography shared concepts |",
    "",
    "## Output Files",
    "",
    "1. `concept_overlap_matrix.csv` - Concept-by-report presence matrix",
    "2. `concept_groups.csv` - Concept normalization groups with included variables",
    "3. `concept_definition_differences.csv` - Pairwise definition comparisons",
    "4. `viz_*.png` - 6 visualization images",
    "5. `concept_eval_summary.md` - This summary document",
]

with open(f"{OUT}/concept_eval_summary.md", 'w') as f:
    f.write('\n'.join(summary_lines))

print("✓ concept_eval_summary.md")
print(f"\n✅ Done! {len(all_concepts)} concepts across {len(report_ids)} VC/funding reports.")
