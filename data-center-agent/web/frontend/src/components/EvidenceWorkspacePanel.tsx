import { useEffect, useState } from "react";
import { getProject } from "../api";
import type { ChatResponse, ConnectorDatasetResult, ConnectorMetricResult, ProjectItem, SourceLink } from "../types";
import { AgentActivityTimeline } from "./AgentActivityTimeline";
import type { DrawerItem } from "./DetailDrawer";
import { ResultSections } from "./ResultSections";
import { SaveToProjectButton } from "./SaveToProjectButton";
import { AvailabilityBadge } from "./cards/AvailabilityBadge";

type TurnLike = {
  query?: string;
  loading?: boolean;
  response?: ChatResponse;
  result_payload?: ChatResponse;
};

type ActiveProject = {
  id: string;
  title: string;
  question?: string;
};

type Props = {
  turn?: TurnLike;
  evidenceItem: DrawerItem | null;
  activeProject?: ActiveProject | null;
  projectId?: string;
  onViewEvidence: (item: DrawerItem) => void;
  onClearEvidence: () => void;
  onAuthRequired?: () => void;
  onSaved: () => void;
  onNavigateProject?: (projectId: string) => void;
};

export function EvidenceWorkspacePanel({
  turn,
  evidenceItem,
  activeProject,
  projectId,
  onViewEvidence,
  onClearEvidence,
  onAuthRequired,
  onSaved,
  onNavigateProject,
}: Props) {
  const response = turn?.response || turn?.result_payload;
  const loading = Boolean(turn?.loading && !response);
  const [projectItems, setProjectItems] = useState<ProjectItem[]>([]);
  const [projectLoading, setProjectLoading] = useState(false);

  async function loadProjectItems() {
    if (!activeProject?.id) {
      setProjectItems([]);
      return;
    }
    setProjectLoading(true);
    try {
      const result = await getProject(activeProject.id);
      setProjectItems(result.items.filter(item => item.item_type !== "note"));
    } catch {
      setProjectItems([]);
    } finally {
      setProjectLoading(false);
    }
  }

  useEffect(() => {
    void loadProjectItems();
  }, [activeProject?.id]);

  function handleSaved() {
    onSaved();
    void loadProjectItems();
  }

  const workspace = response ? normalizeEvidenceWorkspace(response, turn?.query) : undefined;
  const total = workspace ? workspace.totalStructured : 0;
  const hasActiveMessage = Boolean(turn && !loading && response);

  return (
    <aside className="evidence-panel" aria-label="Evidence and data">
      <div className="evidence-panel-body">
        <header className="evidence-panel-head">
          <h2>Evidence &amp; Data</h2>
          {turn?.query && hasActiveMessage && (
            <span className="evidence-query-pill">{turn.query}</span>
          )}
        </header>

        {!turn && !activeProject && (
          <p className="evidence-guidance">
            Select an answer to inspect evidence, data, sources, and actions.
          </p>
        )}

        {!turn && activeProject && (
          <ProjectEvidenceSection
            project={activeProject}
            items={projectItems}
            loading={projectLoading}
            onNavigateProject={onNavigateProject}
          />
        )}

        {turn && loading && (
          <p className="evidence-loading-text">Searching variables, reports, sources, and organizations…</p>
        )}

        {turn && !loading && !response && (
          <p className="evidence-guidance">Waiting for a response…</p>
        )}

        {hasActiveMessage && response?.type === "clarification" && total === 0 && (
          <div className="evidence-context-block">
            <p className="evidence-muted-paragraph">{response.assistant_message || response.message}</p>
            <p className="evidence-hint-inline">Answer in the thread to load structured matches here.</p>
          </div>
        )}

        {hasActiveMessage && response?.type === "error" && (
          <div className="evidence-context-block">
            <p className="evidence-muted-paragraph">{response.assistant_message || response.message}</p>
            <p className="evidence-hint-inline">Use the suggestions in the thread to try another search.</p>
          </div>
        )}

        {hasActiveMessage && response && response.type !== "error" && evidenceItem && (
          <SelectedEvidenceDetail
            item={evidenceItem}
            projectId={projectId}
            onAuthRequired={onAuthRequired}
            onSaved={handleSaved}
            onClear={onClearEvidence}
          />
        )}

        {hasActiveMessage && response && workspace && response.type !== "error" && !evidenceItem && total > 0 && (
          <ActiveMessageWorkspace
            response={response}
            workspace={workspace}
            turnQuery={turn?.query}
            projectId={projectId}
            onViewEvidence={onViewEvidence}
            onAuthRequired={onAuthRequired}
            onSaved={handleSaved}
          />
        )}

        {hasActiveMessage && response && (response.type === "answer" || response.type === "no_results") && !evidenceItem && total === 0 && (
          <div className="evidence-context-block">
            <p className="evidence-no-results-label">No exact match for this message</p>
            <p className="evidence-muted-paragraph">
              No structured variables, reports, or sources matched this query. Try the suggestions in the thread.
            </p>
          </div>
        )}

      </div>
    </aside>
  );
}

function ActiveMessageWorkspace({
  response,
  workspace,
  turnQuery,
  projectId,
  onViewEvidence,
  onAuthRequired,
  onSaved,
}: {
  response: ChatResponse;
  workspace: EvidenceWorkspace;
  turnQuery?: string;
  projectId?: string;
  onViewEvidence: (item: DrawerItem) => void;
  onAuthRequired?: () => void;
  onSaved: () => void;
}) {
  return (
    <div className="evidence-workspace-stack">
      <WorkspaceSection title="Coverage" defaultOpen>
        <div className="coverage-grid">
          <EvidenceStat label="Evidence level" value={workspace.coverage.level} tone={workspace.coverage.level} />
          <EvidenceStat label="Exact data" value={workspace.coverage.exactDataAvailable ? "Yes" : "No"} />
          <EvidenceStat label="External candidates" value={workspace.coverage.externalCandidates.toString()} />
          <EvidenceStat label="Synced data" value={workspace.coverage.syncedData.toString()} />
        </div>
        <p className="evidence-muted-paragraph">{workspace.coverage.explanation}</p>
      </WorkspaceSection>

      <WorkspaceSection title="Key Data" defaultOpen>
        {workspace.computedFindings.length > 0 && (
          <div className="codebook-table flush">
            {workspace.computedFindings.map((item, index) => (
              <MetricRow key={`${item.metric_name || item.title || index}`} item={item} />
            ))}
          </div>
        )}
        {workspace.tables.length > 0 && (
          <div className="evidence-table-stack">
            {workspace.tables.map((table, index) => (
              <DataTablePreview key={index} table={table} />
            ))}
          </div>
        )}
        {workspace.datasets.length > 0 && (
          <div className="dataset-list">
            {workspace.datasets.map((dataset, index) => (
              <DatasetSummary key={`${dataset.source_url || dataset.title || index}`} dataset={dataset} variant="compact" />
            ))}
          </div>
        )}
        {workspace.computedFindings.length === 0 && workspace.tables.length === 0 && workspace.datasets.length === 0 && (
          <p className="evidence-guidance">No computed findings or synced table previews are attached to this answer.</p>
        )}
      </WorkspaceSection>

      <WorkspaceSection title="Evidence" defaultOpen>
        <EvidenceBucket title="Direct evidence" count={workspace.evidence.direct.length} />
        <EvidenceBucket title="Partial evidence" count={workspace.evidence.partial.length} />
        <EvidenceBucket title="Contextual evidence" count={workspace.evidence.contextual.length} />
        <details className="nested-evidence-details">
          <summary>Excluded evidence <span>{workspace.evidence.excluded.length}</span></summary>
          {workspace.evidence.excluded.length === 0 && <p className="evidence-muted-paragraph">No excluded evidence was attached.</p>}
        </details>
        <ResultSections
          results={response.results}
          limitations={response.limitations}
          onViewEvidence={onViewEvidence}
          onAuthRequired={onAuthRequired}
          projectId={projectId}
          onItemSaved={onSaved}
          showLimitationsSection={false}
          className="evidence-full-results"
        />
      </WorkspaceSection>

      <WorkspaceSection title="Sources" defaultOpen>
        <SourceGroup title="Synced official datasets" count={workspace.sources.syncedDatasets.length}>
          {workspace.sources.syncedDatasets.map((dataset, index) => (
            <DatasetSummary key={`${dataset.source_url || dataset.title || index}`} dataset={dataset} />
          ))}
        </SourceGroup>
        <SourceGroup title="Internal reports" count={workspace.sources.internalReports.length}>
          <SourceMiniList items={workspace.sources.internalReports.map((item): SourceMiniItem => ({
            title: item.title || "Report",
            status: "Internal report",
            meta: [item.publisher, item.report_year].filter(Boolean).join(" · "),
            url: item.source_url,
          }))} />
        </SourceGroup>
        <SourceGroup title="Source links" count={workspace.sources.sourceLinks.length}>
          <SourceMiniList items={workspace.sources.sourceLinks.map((item): SourceMiniItem => ({
            title: item.title || item.source_url || "Source",
            status: item.availability || "Source link",
            meta: item.source_type || item.connector_name,
            url: item.source_url,
          }))} />
        </SourceGroup>
        <SourceGroup title="Metadata-only candidates" count={workspace.sources.metadataCandidates.length}>
          <SourceMiniList items={workspace.sources.metadataCandidates.map((item): SourceMiniItem => ({
            title: item.title || item.source_url || "Source candidate",
            status: "Source candidate, not yet synced",
            meta: item.portal || item.provider || item.source_kind,
            url: item.source_url,
          }))} />
        </SourceGroup>
        <SourceGroup title="External candidates" count={workspace.sources.externalCandidates.length}>
          <SourceMiniList items={workspace.sources.externalCandidates.map((item): SourceMiniItem => ({
            title: item.title || item.source_url || "External candidate",
            status: "External candidate",
            meta: item.connector_name || item.source_type,
            url: item.source_url,
          }))} />
        </SourceGroup>
        <SourceGroup title="Organizations" count={workspace.sources.organizations.length}>
          <SourceMiniList items={workspace.sources.organizations.map((item): SourceMiniItem => ({
            title: item.name || item.title || "Organization",
            status: "Organization",
            meta: [item.organization_type, item.geography].filter(Boolean).join(" · "),
            url: item.website_url || item.source_url,
          }))} />
        </SourceGroup>
      </WorkspaceSection>

      <WorkspaceSection title="Actions" defaultOpen>
        <div className="action-grid">
          {workspace.actions.map(action => (
            <button key={action} type="button" className="card-action-btn">{action}</button>
          ))}
          <SaveToProjectButton
            label="Save to project"
            onAuthRequired={onAuthRequired}
            onSaved={onSaved}
            projectId={projectId}
            payload={{
              item_type: "search_result",
              item_id: response.saved_result_id,
              title: turnQuery || response.message || "Saved search",
              metadata: {
                query: turnQuery,
                answer_summary: response.assistant_message || response.message,
                selected_variables: response.results.closest_variables,
                relevant_reports: response.results.relevant_reports,
                organizations: response.results.relevant_organizations,
                source_links: response.results.source_links,
                limitations: response.limitations,
                result_payload: response,
              },
            }}
          />
        </div>
        {workspace.exports.length > 0 && (
          <div className="export-list">
            {workspace.exports.map((item, index) => <span key={index}>{String(item)}</span>)}
          </div>
        )}
      </WorkspaceSection>

      <WorkspaceSection title="Agent Activity">
        <AgentActivityTimeline events={response.tool_trace} defaultCollapsed />
      </WorkspaceSection>
    </div>
  );
}

type EvidenceWorkspace = {
  totalStructured: number;
  coverage: {
    level: "strong" | "partial" | "contextual" | "unresolved";
    explanation: string;
    exactDataAvailable: boolean;
    externalCandidates: number;
    syncedData: number;
  };
  computedFindings: ConnectorMetricResult[];
  tables: unknown[];
  datasets: ConnectorDatasetResult[];
  evidence: {
    direct: unknown[];
    partial: unknown[];
    contextual: unknown[];
    excluded: unknown[];
  };
  sources: {
    syncedDatasets: ConnectorDatasetResult[];
    internalReports: ChatResponse["results"]["relevant_reports"];
    sourceLinks: SourceLink[];
    metadataCandidates: ConnectorDatasetResult[];
    externalCandidates: SourceLink[];
    organizations: ChatResponse["results"]["relevant_organizations"];
  };
  actions: string[];
  exports: unknown[];
};

function normalizeEvidenceWorkspace(response: ChatResponse, query?: string): EvidenceWorkspace {
  const r = response.results;
  const connectorDatasets = r.connector_datasets || [];
  const connectorCandidates = r.connector_candidates || [];
  const tavilyResults = r.tavily_candidates?.results || [];
  const syncedDatasets = connectorDatasets.filter(item => !isMetadataOnlyConnector(item));
  const metadataDatasets = connectorDatasets.filter(isMetadataOnlyConnector);
  const metadataCandidates = [...connectorCandidates, ...metadataDatasets];
  const direct = [...r.closest_variables, ...(r.connector_metrics || []), ...syncedDatasets];
  const partial = [...r.relevant_reports, ...r.source_links];
  const contextual = [...r.relevant_organizations, ...tavilyResults, ...metadataCandidates];
  const comparison = r.comparison || {};
  const comparisonTables = Object.entries(comparison)
    .filter(([, value]) => Array.isArray(value) || isRecord(value))
    .map(([name, value]) => ({ name, value }));
  const debugExports = Array.isArray((response.debug as Record<string, unknown> | undefined)?.exports)
    ? ((response.debug as Record<string, unknown>).exports as unknown[])
    : [];
  const totalStructured = direct.length + partial.length + contextual.length + comparisonTables.length;
  const level = direct.length > 0
    ? "strong"
    : partial.length > 0
      ? "partial"
      : contextual.length > 0
        ? "contextual"
        : "unresolved";

  return {
    totalStructured,
    coverage: {
      level,
      explanation: coverageExplanation(level, direct.length, partial.length, contextual.length, query),
      exactDataAvailable: direct.length > 0,
      externalCandidates: metadataCandidates.length + tavilyResults.length,
      syncedData: syncedDatasets.length,
    },
    computedFindings: r.connector_metrics || [],
    tables: comparisonTables,
    datasets: connectorDatasets,
    evidence: {
      direct,
      partial,
      contextual,
      excluded: response.limitations || [],
    },
    sources: {
      syncedDatasets,
      internalReports: r.relevant_reports,
      sourceLinks: r.source_links,
      metadataCandidates,
      externalCandidates: [...r.source_links.filter(isFallbackWebResult), ...tavilyResults],
      organizations: r.relevant_organizations,
    },
    actions: buildActions(response, syncedDatasets.length, metadataCandidates.length),
    exports: debugExports,
  };
}

function WorkspaceSection({ title, defaultOpen = false, children }: { title: string; defaultOpen?: boolean; children: React.ReactNode }) {
  return (
    <details className="workspace-section" open={defaultOpen}>
      <summary>{title}</summary>
      <div className="workspace-section-body">{children}</div>
    </details>
  );
}

function EvidenceStat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className={`evidence-stat${tone ? ` evidence-stat-${tone}` : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function EvidenceBucket({ title, count }: { title: string; count: number }) {
  return (
    <div className="evidence-bucket-row">
      <span>{title}</span>
      <strong>{count}</strong>
    </div>
  );
}

function SourceGroup({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  if (count === 0) return null;
  return (
    <section className="source-group">
      <h3>{title} <span>{count}</span></h3>
      {children}
    </section>
  );
}

type SourceMiniItem = {
  title: string;
  status?: string | null;
  meta?: string | number | null;
  url?: string | null;
};

function SourceMiniList({ items }: { items: SourceMiniItem[] }) {
  return (
    <ul className="source-mini-list">
      {items.map((item, index) => (
        <li key={`${item.title}-${index}`}>
          <div className="source-mini-main">
            {item.status && <span className="source-status-chip">{item.status}</span>}
            <strong>{item.title}</strong>
            {item.meta && <span className="source-mini-meta">{String(item.meta)}</span>}
          </div>
          {item.url && (
            <a className="source-card-action" href={item.url} target="_blank" rel="noreferrer">
              Open source
            </a>
          )}
        </li>
      ))}
    </ul>
  );
}

function DatasetSummary({ dataset, variant = "full" }: { dataset: ConnectorDatasetResult; variant?: "full" | "compact" }) {
  const fields = fieldsUsed(dataset);
  const metadataOnly = isMetadataOnlyConnector(dataset);
  return (
    <article className={`dataset-summary-card dataset-summary-card-${variant}`}>
      <div className="source-card-topline">
        <span className={`source-status-chip${metadataOnly ? " source-status-muted" : ""}`}>
          {metadataOnly ? "Source candidate, not yet synced" : "Synced official dataset"}
        </span>
        {(dataset.portal || dataset.provider) && <span className="source-origin-text">{dataset.portal || dataset.provider}</span>}
      </div>
      <h3>{dataset.title || dataset.source_url || "Dataset"}</h3>
      <div className="dataset-meta-grid">
        {dataset.retrieved_at && <span>Retrieved {formatShortDate(dataset.retrieved_at)}</span>}
        {(dataset as Record<string, unknown>).snapshot_id && <span>Snapshot {String((dataset as Record<string, unknown>).snapshot_id)}</span>}
        {(dataset.row_count !== undefined || dataset.column_count !== undefined) && (
          <span>{dataset.row_count ?? "?"} x {dataset.column_count ?? "?"}</span>
        )}
        {fields && <span>Fields used: {fields}</span>}
      </div>
      {dataset.source_url && (
        <a className="source-card-action" href={dataset.source_url} target="_blank" rel="noreferrer">
          Open source
        </a>
      )}
    </article>
  );
}

function MetricRow({ item }: { item: ConnectorMetricResult }) {
  return (
    <article className="codebook-row">
      <div>
        <strong>{item.metric_name || item.title || "Computed finding"}</strong>
        {item.metric_description && <p>{item.metric_description}</p>}
      </div>
      <div className="codebook-row-meta">
        {item.dataset_name && <span>{item.dataset_name}</span>}
        {(item.portal || item.provider) && <span>{item.portal || item.provider}</span>}
        {item.category && <span>{item.category}</span>}
        {item.retrieved_at && <span>{formatShortDate(item.retrieved_at)}</span>}
      </div>
    </article>
  );
}

function DataTablePreview({ table }: { table: unknown }) {
  const name = isRecord(table) && typeof table.name === "string" ? table.name : "Table";
  const value = isRecord(table) ? table.value : table;
  if (Array.isArray(value)) {
    const rows = value.slice(0, 6).filter(isRecord);
    const columns = [...new Set(rows.flatMap(row => Object.keys(row)))].slice(0, 6);
    return (
      <div className="evidence-data-table">
        <h3>{name}</h3>
        <table>
          <thead>
            <tr>{columns.map(col => <th key={col}>{col}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex}>{columns.map(col => <td key={col}>{formatCell(row[col])}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return (
    <div className="evidence-data-table">
      <h3>{name}</h3>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}

function buildActions(response: ChatResponse, syncedCount: number, metadataCount: number): string[] {
  const actions = ["Export Excel", "Export CSV", "Save to project"];
  if (metadataCount > 0) actions.push("Pull latest official data", "Ingest source");
  if (syncedCount > 0) actions.push("Compare definitions");
  if (response.type === "no_results") actions.push("Broaden search");
  actions.push("Narrow search", "Create source discovery task");
  return [...new Set(actions)];
}

function coverageExplanation(level: EvidenceWorkspace["coverage"]["level"], direct: number, partial: number, contextual: number, query?: string) {
  const suffix = query ? ` for "${query}"` : "";
  if (level === "strong") return `${direct} direct evidence item${direct === 1 ? "" : "s"} available${suffix}.`;
  if (level === "partial") return `${partial} partial evidence item${partial === 1 ? "" : "s"} available${suffix}.`;
  if (level === "contextual") return `${contextual} contextual item${contextual === 1 ? "" : "s"} available${suffix}.`;
  return `No structured evidence is attached${suffix}.`;
}

function isMetadataOnlyConnector(item: ConnectorDatasetResult) {
  const text = `${item.data_status_label || ""} ${item.data_status || ""}`.toLowerCase();
  return text.includes("metadata") || (item.row_count == null && item.column_count == null);
}

function isFallbackWebResult(item: SourceLink) {
  const text = `${item.connector_name || ""} ${item.source_url || ""} ${item.title || ""}`.toLowerCase();
  return text.includes("tavily");
}

function fieldsUsed(dataset: ConnectorDatasetResult) {
  const raw = (dataset as Record<string, unknown>).fields_used || (dataset as Record<string, unknown>).columns_used || (dataset as Record<string, unknown>).fields;
  if (Array.isArray(raw)) return raw.map(String).slice(0, 8).join(", ");
  if (typeof raw === "string") return raw;
  return undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function formatCell(value: unknown) {
  if (value == null) return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function formatShortDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 10);
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function SelectedEvidenceDetail({
  item,
  projectId,
  onAuthRequired,
  onSaved,
  onClear,
}: {
  item: DrawerItem;
  projectId?: string;
  onAuthRequired?: () => void;
  onSaved: () => void;
  onClear: () => void;
}) {
  const title = drawerItemTitle(item);
  const url = drawerItemUrl(item);
  const typeLabel = typeLabelFor(item.kind);
  const [copyStatus, setCopyStatus] = useState("");

  async function copyCitation() {
    try {
      await navigator.clipboard.writeText(buildCitation(item));
      setCopyStatus("Copied");
      window.setTimeout(() => setCopyStatus(""), 2000);
    } catch {
      setCopyStatus("Copy failed");
    }
  }

  return (
    <article className="evidence-detail evidence-detail-full">
      <div className="evidence-detail-head">
        <div>
          <span className={`result-preview-type rt-${item.kind === "organization" ? "organization" : item.kind}`}>
            {typeLabel}
          </span>
          <h3>{title}</h3>
        </div>
        <button type="button" className="plain-action evidence-back-btn" onClick={onClear}>
          Back
        </button>
      </div>

      {item.kind === "variable" && (
        <>
          {item.data.availability && <AvailabilityBadge value={item.data.availability} />}
          <EvidenceField label="Definition" value={item.data.definition} />
          <EvidenceField label="Measurement method" value={item.data.measurement_method} />
          <EvidenceField label="Data source" value={item.data.data_source} />
          <EvidenceField
            label="Geography / time"
            value={[item.data.geographic_coverage, item.data.temporal_coverage].filter(Boolean).join(" · ")}
          />
          <EvidenceQuote value={item.data.evidence_quote} />
        </>
      )}

      {item.kind === "report" && (
        <>
          <EvidenceField label="Description" value={item.data.why_it_matched} />
          <EvidenceField label="Publisher" value={item.data.publisher} />
          <EvidenceField label="Year" value={item.data.report_year} />
          <EvidenceField label="Geography" value={item.data.geography || item.data.geographic_coverage} />
          <EvidenceQuote value={item.data.why_it_matched} />
        </>
      )}

      {item.kind === "organization" && (
        <>
          <EvidenceField label="Type" value={item.data.organization_type} />
          <EvidenceField label="Description" value={item.data.description} />
          <EvidenceField label="Geography" value={item.data.geography} />
        </>
      )}

      {item.kind === "source" && (
        <>
          {item.data.availability && <AvailabilityBadge value={item.data.availability} />}
          <EvidenceField label="Source" value={item.data.title || item.data.source_url} />
        </>
      )}

      {url && <EvidenceField label="Source URL" value={url} />}

      <div className="evidence-detail-actions">
        <SaveToProjectButton
          label="Save to project"
          onAuthRequired={onAuthRequired}
          onSaved={onSaved}
          projectId={projectId}
          payload={savePayloadForItem(item)}
        />
        {url && (
          <a className="card-action-link" href={url} target="_blank" rel="noreferrer">
            Open source
          </a>
        )}
        <button type="button" className="card-action-btn" onClick={() => void copyCitation()}>
          {copyStatus || "Copy citation"}
        </button>
      </div>
    </article>
  );
}

function ProjectEvidenceSection({
  project,
  items,
  loading,
  onNavigateProject,
  compact = false,
}: {
  project: ActiveProject;
  items: ProjectItem[];
  loading: boolean;
  onNavigateProject?: (projectId: string) => void;
  compact?: boolean;
}) {
  return (
    <section className={`evidence-project-section${compact ? " evidence-project-section-compact" : ""}`}>
      <div className="evidence-project-head">
        <div>
          <h3 className="evidence-result-section-title">Project evidence</h3>
          <p className="evidence-project-name">{project.title}</p>
          {project.question && !compact && (
            <p className="evidence-muted-paragraph">{project.question}</p>
          )}
        </div>
        {onNavigateProject && (
          <button type="button" className="plain-action" onClick={() => onNavigateProject(project.id)}>
            View project
          </button>
        )}
      </div>
      {loading && <p className="evidence-hint-inline">Loading saved evidence…</p>}
      {!loading && items.length === 0 && (
        <p className="evidence-guidance">Saved variables, reports, and searches from this project will appear here.</p>
      )}
      {!loading && items.length > 0 && (
        <ul className="evidence-result-list">
          {items.slice(0, compact ? 5 : 12).map(item => (
            <li key={item.id}>
              <div className="evidence-result-row evidence-result-row-static">
                <span className={`result-preview-type rt-${evidenceTypeClass(item.item_type)}`}>
                  {evidenceTypeLabel(item.item_type)}
                </span>
                <strong>{item.title || item.item_type}</strong>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function typeLabelFor(kind: DrawerItem["kind"]) {
  const map = { variable: "Variable", report: "Report", organization: "Organization", source: "Source" };
  return map[kind];
}

function evidenceTypeLabel(type: ProjectItem["item_type"]) {
  const map: Record<string, string> = {
    variable: "Var",
    report: "Rep",
    organization: "Org",
    source: "Src",
    search_result: "Search",
  };
  return map[type] || type;
}

function evidenceTypeClass(type: ProjectItem["item_type"]) {
  if (type === "variable") return "variable";
  if (type === "report") return "report";
  if (type === "organization") return "organization";
  return "source";
}

function drawerItemTitle(item: DrawerItem) {
  if (item.kind === "variable") return item.data.title || item.data.raw_variable_name || "Variable";
  if (item.kind === "report") return item.data.title || "Report";
  if (item.kind === "organization") return item.data.name || item.data.title || "Organization";
  return item.data.title || item.data.source_url || "Source";
}

function drawerItemUrl(item: DrawerItem) {
  if (item.kind === "variable") return item.data.source_url;
  if (item.kind === "report") return item.data.source_url;
  if (item.kind === "organization") return item.data.website_url || item.data.source_url;
  return item.data.source_url;
}

function buildCitation(item: DrawerItem) {
  const title = drawerItemTitle(item);
  const url = drawerItemUrl(item);
  const parts = [title];
  if (item.kind === "variable") {
    if (item.data.data_source) parts.push(item.data.data_source);
    if (item.data.definition) parts.push(item.data.definition);
  }
  if (item.kind === "report" && item.data.publisher) parts.push(item.data.publisher);
  if (url) parts.push(url);
  return parts.filter(Boolean).join(". ");
}

function savePayloadForItem(item: DrawerItem) {
  const title = drawerItemTitle(item);
  if (item.kind === "variable") {
    const id = item.data.id || item.data.object_id || item.data.variable_id;
    return { item_type: "variable" as const, item_id: id, title, metadata: { variable: item.data } };
  }
  if (item.kind === "report") {
    const id = item.data.id || item.data.object_id || item.data.report_id;
    return { item_type: "report" as const, item_id: id, title, metadata: { report: item.data } };
  }
  if (item.kind === "organization") {
    const id = item.data.id || item.data.object_id || item.data.organization_id;
    return { item_type: "organization" as const, item_id: id, title, metadata: { organization: item.data } };
  }
  const id = item.data.id || item.data.object_id || item.data.source_id;
  return { item_type: "source" as const, item_id: id, title, metadata: { source: item.data } };
}

function EvidenceField({ label, value }: { label: string; value?: string | number | null }) {
  if (!value) return null;
  return (
    <div className="evidence-field">
      <span>{label}</span>
      <p>{String(value)}</p>
    </div>
  );
}

function EvidenceQuote({ value }: { value?: string | null }) {
  if (!value) return null;
  return <blockquote className="drawer-evidence">{value}</blockquote>;
}
