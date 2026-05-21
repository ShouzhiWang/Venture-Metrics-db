#!/usr/bin/env python3
"""Generate visualizations for concept overlap evaluation."""

import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from collections import Counter
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Load data ---
overlap = pd.read_csv(f"{OUT_DIR}/concept_overlap_matrix.csv")
groups = pd.read_csv(f"{OUT_DIR}/concept_groups.csv")

# Parse overlap matrix
report_cols = [c for c in overlap.columns if c != 'concept_id' and c != 'concept_name']

# Binary matrix: present/absent — use str.contains for robustness
binary_df = pd.DataFrame(index=overlap['concept_id'])
binary_df['concept_name'] = overlap['concept_name'].values
for col in report_cols:
    binary_df[col] = overlap[col].str.contains('present', na=False).astype(int).values

# Short labels for reports
short_labels = {
    'venture_funding_sg_2022': 'Venture\nFunding\n(SG 2022)',
    'startups_southeast_2025': 'Startups\nSE US\n(2025)',
    'uk_innovation_strategy_2021': 'UK Innovation\nStrategy\n(2021)',
    'longitudinal_sme_survey_2024': 'SME Survey\n(UK 2024)',
    'sg_digital_economy_2024': 'SG Digital\nEconomy\n(2024)',
}

labels = list(short_labels.keys())

# ===== 1. HEATMAP =====
fig, ax = plt.subplots(figsize=(12, 10))

data = binary_df[labels].values
concept_labels = binary_df['concept_name'].values

cmap = matplotlib.colors.ListedColormap(['#f0f0f0', '#2196F3'])
bounds = [-0.5, 0.5, 1.5]
norm = matplotlib.colors.BoundaryNorm(bounds, cmap.N)

im = ax.imshow(data, cmap=cmap, norm=norm, aspect='auto')

ax.set_xticks(range(len(labels)))
ax.set_xticklabels([short_labels[l] for l in labels], fontsize=9, ha='center')
ax.set_yticks(range(len(concept_labels)))
ax.set_yticklabels(concept_labels, fontsize=9)

for i in range(len(concept_labels)):
    for j in range(len(labels)):
        val = data[i, j]
        color = 'white' if val == 1 else '#999999'
        symbol = '●' if val == 1 else '—'
        ax.text(j, i, symbol, ha='center', va='center', fontsize=11, color=color, fontweight='bold')

ax.set_title('Concept Presence Across Reports\n(● = Present, — = Absent)', fontsize=14, fontweight='bold', pad=15)
ax.spines[:].set_visible(False)
ax.tick_params(top=False, bottom=False, left=False, right=False)

legend_elements = [
    mpatches.Patch(facecolor='#2196F3', edgecolor='gray', label='Present'),
    mpatches.Patch(facecolor='#f0f0f0', edgecolor='gray', label='Absent'),
]
ax.legend(handles=legend_elements, loc='lower right', fontsize=10, framealpha=0.9)

plt.tight_layout()
plt.savefig(f"{OUT_DIR}/viz_concept_heatmap.png", dpi=150, bbox_inches='tight', facecolor='white')
plt.close()
print("✓ viz_concept_heatmap.png")

# ===== 2. CONCEPTS PER REPORT (horizontal bar) =====
fig, ax = plt.subplots(figsize=(10, 5))

counts = [int(binary_df[col].sum()) for col in labels]
colors = ['#1565C0', '#2196F3', '#64B5F6', '#90CAF9', '#BBDEFB']
bars = ax.barh([short_labels[l].replace('\n', ' ') for l in labels], counts, color=colors, edgecolor='white', height=0.6)

for bar, count in zip(bars, counts):
    ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height()/2, str(int(count)),
            va='center', fontsize=11, fontweight='bold', color='#333')

ax.set_xlabel('Number of Concepts', fontsize=11)
ax.set_title('Concept Count by Report', fontsize=14, fontweight='bold')
ax.set_xlim(0, max(counts) + 2)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/viz_concepts_per_report.png", dpi=150, bbox_inches='tight', facecolor='white')
plt.close()
print("✓ viz_concepts_per_report.png")

# ===== 3. OVERLAP FREQUENCY BAR CHART =====
fig, ax = plt.subplots(figsize=(8, 5))

concept_freq = binary_df[labels].astype(int).sum(axis=1)
freq_counts = concept_freq.value_counts().sort_index()

ax.bar(freq_counts.index.astype(str), freq_counts.values, color='#FF7043', edgecolor='white', width=0.5)
for x, y in zip(freq_counts.index.astype(str), freq_counts.values):
    ax.text(int(x), y + 0.3, str(y), ha='center', fontsize=11, fontweight='bold', color='#333')

ax.set_xlabel('Number of Reports Containing Concept', fontsize=11)
ax.set_ylabel('Number of Concepts', fontsize=11)
ax.set_title('Concept Overlap Distribution\n(How many reports share each concept)', fontsize=14, fontweight='bold')
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/viz_overlap_distribution.png", dpi=150, bbox_inches='tight', facecolor='white')
plt.close()
print("✓ viz_overlap_distribution.png")

# ===== 4. SHARED CONCEPTS PAIR OVERLAP MATRIX =====
fig, ax = plt.subplots(figsize=(8, 7))

n = len(labels)
matrix = np.zeros((n, n), dtype=int)
shared_concepts = binary_df[labels].values.astype(int)

for i in range(n):
    for j in range(n):
        if i == j:
            matrix[i][j] = int(shared_concepts[:, i].sum())
        else:
            matrix[i][j] = int(np.sum(shared_concepts[:, i] & shared_concepts[:, j]))

im = ax.imshow(matrix, cmap='YlOrRd', aspect='auto')
short = [short_labels[l].replace('\n', ' ') for l in labels]

ax.set_xticks(range(n))
ax.set_xticklabels(short, rotation=30, ha='right', fontsize=9)
ax.set_yticks(range(n))
ax.set_yticklabels(short, fontsize=9)

for i in range(n):
    for j in range(n):
        val = matrix[i][j]
        color = 'white' if val > 2 else '#333'
        ax.text(j, i, str(val), ha='center', va='center', fontsize=12, fontweight='bold', color=color)

ax.set_title('Report Pair Overlap Matrix\n(Number of Shared Concepts)', fontsize=14, fontweight='bold', pad=15)
plt.colorbar(im, ax=ax, shrink=0.7, label='Shared Concepts')
ax.spines[:].set_visible(False)
ax.tick_params(top=False, bottom=False, left=False, right=False)

plt.tight_layout()
plt.savefig(f"{OUT_DIR}/viz_pair_overlap_matrix.png", dpi=150, bbox_inches='tight', facecolor='white')
plt.close()
print("✓ viz_pair_overlap_matrix.png")

# ===== 5. DEFINITION DIFFERENCES CHART =====
fig, ax = plt.subplots(figsize=(10, 5))

shared = ['C01', 'C02', 'C03', 'C05', 'C06']
shared_names = ['VC Deal\nVolume', 'Total VC\nInvestment', 'Avg Deal\nSize', 'Sector\nDistribution', 'Stage\nDistribution']
n_reports_in = [2, 3, 2, 2, 2]
unique_defs = [2, 3, 2, 2, 2]

x = np.arange(len(shared_names))
width = 0.35

bars1 = ax.bar(x - width/2, n_reports_in, width, label='Reports with Concept', color='#42A5F5', edgecolor='white')
bars2 = ax.bar(x + width/2, unique_defs, width, label='Unique Definitions', color='#EF5350', edgecolor='white')

for bar, val in zip(bars1, n_reports_in):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1, str(val),
            ha='center', fontsize=10, fontweight='bold')
for bar, val in zip(bars2, unique_defs):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1, str(val),
            ha='center', fontsize=10, fontweight='bold')

ax.set_xticks(x)
ax.set_xticklabels(shared_names, fontsize=10)
ax.set_ylabel('Count', fontsize=11)
ax.set_title('Shared Concepts: Reports vs Unique Definitions\n(Even shared concepts have different definitions)', fontsize=13, fontweight='bold')
ax.legend(fontsize=10)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/viz_definition_differences.png", dpi=150, bbox_inches='tight', facecolor='white')
plt.close()
print("✓ viz_definition_differences.png")

# ===== 6. CONCEPT DOMAIN TAXONOMY (stacked bar) =====
fig, ax = plt.subplots(figsize=(10, 6))

domains = {
    'Venture Capital / Funding': ['C01', 'C02', 'C03', 'C04', 'C05', 'C06', 'C07'],
    'Government / Policy': ['C08', 'C09', 'C10', 'C11', 'C12', 'C24'],
    'SME Performance': ['C13', 'C14', 'C15', 'C16', 'C17', 'C18', 'C19', 'C20'],
    'Digital Economy': ['C21', 'C22', 'C23'],
}

domain_colors = {
    'Venture Capital / Funding': '#1565C0',
    'Government / Policy': '#2E7D32',
    'SME Performance': '#E65100',
    'Digital Economy': '#6A1B9A',
}

report_labels = [short_labels[l].replace('\n', ' ') for l in labels]
domain_presence = {d: [] for d in domains}

for label in labels:
    for domain, cids in domains.items():
        count = sum(1 for cid in cids if cid in binary_df.index and binary_df.loc[cid, label] == 1)
        domain_presence[domain].append(count)

bottom = np.zeros(len(labels))
for domain, counts in domain_presence.items():
    ax.bar(range(len(labels)), counts, bottom=bottom, label=domain,
           color=domain_colors[domain], edgecolor='white', width=0.6)
    bottom += np.array(counts)

ax.set_xticks(range(len(labels)))
ax.set_xticklabels(report_labels, rotation=20, ha='right', fontsize=9)
ax.set_ylabel('Number of Concepts', fontsize=11)
ax.set_title('Concept Domain Distribution by Report', fontsize=14, fontweight='bold')
ax.legend(fontsize=9, loc='upper right')
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/viz_domain_distribution.png", dpi=150, bbox_inches='tight', facecolor='white')
plt.close()
print("✓ viz_domain_distribution.png")

# ===== 7. WORD CLOUD OF CONCEPTS =====
from wordcloud import WordCloud

freq_dict = {}
for _, row in groups.iterrows():
    n_vars = len(str(row['included_variables']).split(';'))
    freq_dict[row['concept_name']] = max(n_vars, 2)

wc = WordCloud(width=1200, height=600, background_color='white',
               colormap='viridis', max_words=30, min_font_size=10,
               prefer_horizontal=0.7, margin=10)
wc.generate_from_frequencies(freq_dict)

fig, ax = plt.subplots(figsize=(12, 6))
ax.imshow(wc, interpolation='bilinear')
ax.axis('off')
ax.set_title('Concept Word Cloud\n(scaled by number of measured variables per concept)', fontsize=14, fontweight='bold', pad=15)
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/viz_concept_wordcloud.png", dpi=150, bbox_inches='tight', facecolor='white')
plt.close()
print("✓ viz_concept_wordcloud.png")

print("\n✅ All 7 visualizations generated in", OUT_DIR)
