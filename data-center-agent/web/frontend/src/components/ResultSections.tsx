import type { ChatResponse, ConnectorDatasetResult, ConnectorMetricResult, SourceLink } from "../types";
import type { DrawerItem } from "./DetailDrawer";
import { OrganizationCard } from "./cards/OrganizationCard";
import { ReportCard } from "./cards/ReportCard";
import { SourceCard } from "./cards/SourceCard";
import { VariableCard } from "./cards/VariableCard";

type Props = {
  results: ChatResponse["results"];
  limitations: string[];
  onViewEvidence: (item: DrawerItem) => void;
  onAuthRequired?: () => void;
  /** When set, cards save directly to this project without a picker */
  projectId?: string;
  /** Called after any card item is saved */
  onItemSaved?: () => void;
  /** When false, omit the collapsible Limitations section (shown elsewhere). */
  showLimitationsSection?: boolean;
  className?: string;
};

export function ResultSections({
  results,
  limitations,
  onViewEvidence,
  onAuthRequired,
  projectId,
  onItemSaved,
  showLimitationsSection = true,
  className,
}: Props) {
  const comparison = results.comparison || {};
  const connectorDatasets = results.connector_datasets || [];
  const connectorMetrics = results.connector_metrics || [];
  const connectorCandidates = results.connector_candidates || [];
  const tavilyResults = results.tavily_candidates?.results || [];
  const researchResults = connectorDatasets.filter(isAcademicResult);
  const officialDataResults = connectorDatasets.filter(item => !isAcademicResult(item));
  const semanticMatches = results.source_links.filter(item => !isFallbackWebResult(item));
  const hasComparison = Object.keys(comparison).length > 0;

  const definitionDifferences = Array.isArray(comparison.definition_differences)
    ? (comparison.definition_differences as { raw_variable_name?: string; definition?: string }[])
    : [];

  const totalResults = results.closest_variables.length
    + results.relevant_reports.length
    + results.relevant_organizations.length
    + results.source_links.length
    + connectorDatasets.length
    + connectorMetrics.length
    + connectorCandidates.length
    + tavilyResults.length;
  if (totalResults === 0 && !hasComparison) return null;

  return (
    <div className={`result-groups${className ? ` ${className}` : ""}`}>
      {results.relevant_reports.length > 0 && (
        <details className="result-group" open>
          <summary>Internal Reports <span>{results.relevant_reports.length}</span></summary>
          <div className="card-grid">
            {results.relevant_reports.map((item, index) => (
              <ReportCard
                key={`${item.title}-${index}`}
                report={item}
                onViewEvidence={() => onViewEvidence({ kind: "report", data: item })}
                onAuthRequired={onAuthRequired}
                projectId={projectId}
                onSaved={onItemSaved}
              />
            ))}
          </div>
        </details>
      )}

      {semanticMatches.length > 0 && (
        <details className="result-group" open>
          <summary>Semantic Matches <span>{semanticMatches.length}</span></summary>
          <div className="card-grid compact">
            {semanticMatches.map((item, index) => (
              <SourceCard
                key={`${item.source_url}-${index}`}
                source={item}
                onViewEvidence={() => onViewEvidence({ kind: "source", data: item })}
                onAuthRequired={onAuthRequired}
                projectId={projectId}
                onSaved={onItemSaved}
              />
            ))}
          </div>
        </details>
      )}

      {officialDataResults.length > 0 && (
        <details className="result-group" open>
          <summary>Official Data APIs <span>{officialDataResults.length}</span></summary>
          <div className="card-grid">
            {officialDataResults.map((item, index) => (
              <ConnectorDataCard
                key={`${item.source_url || item.title}-${index}`}
                item={item}
                onViewEvidence={() => onViewEvidence({ kind: "source", data: item })}
              />
            ))}
          </div>
        </details>
      )}

      {connectorMetrics.length > 0 && (
        <details className="result-group" open>
          <summary>Connector Metrics <span>{connectorMetrics.length}</span></summary>
          <div className="codebook-table">
            {connectorMetrics.map((item, index) => (
              <MetricRow key={`${item.metric_name || item.title}-${index}`} item={item} />
            ))}
          </div>
        </details>
      )}

      {researchResults.length > 0 && (
        <details className="result-group" open>
          <summary>Research Publications <span>{researchResults.length}</span></summary>
          <div className="card-grid">
            {researchResults.map((item, index) => (
              <AcademicCard
                key={`${item.source_url || item.title}-${index}`}
                item={item}
                onViewEvidence={() => onViewEvidence({ kind: "source", data: item })}
              />
            ))}
          </div>
        </details>
      )}

      {results.closest_variables.length > 0 && (
        <details className="result-group" open>
          <summary>Variables & Codebook <span>{results.closest_variables.length}</span></summary>
          <div className="codebook-table">
            {results.closest_variables.map((item, index) => (
              <VariableCard
                key={`${item.title}-${index}`}
                variable={item}
                onViewEvidence={() => onViewEvidence({ kind: "variable", data: item })}
                onAuthRequired={onAuthRequired}
                projectId={projectId}
                onSaved={onItemSaved}
              />
            ))}
          </div>
        </details>
      )}

      {results.relevant_organizations.length > 0 && (
        <details className="result-group">
          <summary>Organizations <span>{results.relevant_organizations.length}</span></summary>
          <div className="card-grid">
            {results.relevant_organizations.map((item, index) => (
              <OrganizationCard
                key={`${item.name}-${index}`}
                organization={item}
                onViewEvidence={() => onViewEvidence({ kind: "organization", data: item })}
                onAuthRequired={onAuthRequired}
                projectId={projectId}
                onSaved={onItemSaved}
              />
            ))}
          </div>
        </details>
      )}

      {connectorCandidates.length > 0 && (
        <details className="result-group">
          <summary>Connector Candidates <span>{connectorCandidates.length}</span></summary>
          <div className="card-grid compact">
            {connectorCandidates.map((item, index) => (
              <ConnectorDataCard
                key={`${item.source_url || item.title}-${index}`}
                item={item}
                onViewEvidence={() => onViewEvidence({ kind: "source", data: item })}
              />
            ))}
          </div>
        </details>
      )}

      {tavilyResults.length > 0 && (
        <details className="result-group" open>
          <summary>Fallback Web Search <span>{tavilyResults.length}</span></summary>
          {results.tavily_candidates?.note && (
            <p className="fallback-note">{results.tavily_candidates.note}</p>
          )}
          <div className="card-grid compact">
            {tavilyResults.map((item, index) => (
              <ConnectorDataCard
                key={`${item.source_url || item.title}-${index}`}
                item={{ ...item, portal: item.portal || "Tavily", data_status_label: "Fallback Web Search" }}
                onViewEvidence={() => onViewEvidence({ kind: "source", data: item })}
              />
            ))}
          </div>
        </details>
      )}

      {hasComparison && (
        <details className="result-group">
          <summary>Comparison <span>1</span></summary>
          <div className="comparison-block">
            <p>{String(comparison.summary ?? "Comparison available.")}</p>
            <dl>
              <dt>Comparability</dt>
              <dd>{String(comparison.comparability ?? "unknown")}</dd>
            </dl>
            {definitionDifferences.length > 0 && (
              <ul>
                {definitionDifferences.slice(0, 5).map((item, index) => (
                  <li key={index}>
                    <strong>{item.raw_variable_name ?? "Variable"}:</strong>{" "}
                    {item.definition ?? "No definition available"}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </details>
      )}

      {showLimitationsSection && limitations.length > 0 && (
        <details className="result-group limitations-group">
          <summary>Limitations <span>{limitations.length}</span></summary>
          <div className="limitations-inline">
            <ul>
              {limitations.map((item, i) => <li key={i}>{item}</li>)}
            </ul>
          </div>
        </details>
      )}
    </div>
  );
}

function isAcademicResult(item: ConnectorDatasetResult): boolean {
  const text = `${item.portal || ""} ${item.provider || ""} ${item.source_url || ""} ${item.data_status_label || ""}`.toLowerCase();
  return text.includes("openalex") || text.includes("crossref") || text.includes("doi.org");
}

function isFallbackWebResult(item: SourceLink): boolean {
  const text = `${item.connector_name || ""} ${item.source_url || ""} ${item.title || ""}`.toLowerCase();
  return text.includes("tavily");
}

function portalLabel(item: ConnectorDatasetResult | ConnectorMetricResult): string {
  const text = `${item.portal || ""} ${item.provider || ""} ${item.source_url || ""} ${item.data_status_label || ""}`.toLowerCase();
  if (text.includes("data.gov.hk")) return "data.gov.hk";
  if (text.includes("data.gov.sg")) return "data.gov.sg";
  if (text.includes("world bank") || text.includes("worldbank")) return "World Bank";
  if (text.includes("openalex")) return "OpenAlex";
  if (text.includes("crossref")) return "Crossref";
  if (text.includes("tavily")) return "Tavily";
  return item.portal || item.provider || "Connector";
}

function ConnectorDataCard({ item, onViewEvidence }: { item: ConnectorDatasetResult; onViewEvidence: () => void }) {
  const portal = portalLabel(item);
  const trusted = portal !== "Tavily";
  return (
    <article className="result-card research-card">
      <div className="badge-row">
        <span className="source-badge">{trusted ? "Official Data API" : "Fallback Web Search"}</span>
        <span className="source-badge muted">{portal}</span>
        {item.data_status_label && <span className="source-badge muted">{item.data_status_label}</span>}
      </div>
      <h4>{item.title || "Connector result"}</h4>
      {(item.why_it_matched || item.definition || item.data_source) && (
        <p className="card-def">{item.why_it_matched || item.definition || item.data_source}</p>
      )}
      <div className="card-meta">
        {item.row_count !== undefined && <span className="meta-chip">{item.row_count} rows</span>}
        {item.column_count !== undefined && <span className="meta-chip">{item.column_count} columns</span>}
        {item.retrieved_at && <span className="meta-chip">Retrieved {formatShortDate(item.retrieved_at)}</span>}
        {item.last_modified && <span className="meta-chip">Modified {formatShortDate(item.last_modified)}</span>}
        {item.availability && <span className="meta-chip">{item.availability}</span>}
      </div>
      <div className="card-actions">
        <button type="button" className="card-action-btn" onClick={onViewEvidence}>View details</button>
        {(item.download_url || item.source_url) && (
          <a href={item.download_url || item.source_url} target="_blank" rel="noreferrer" className="card-action-link">
            Open source
          </a>
        )}
      </div>
    </article>
  );
}

function AcademicCard({ item, onViewEvidence }: { item: ConnectorDatasetResult; onViewEvidence: () => void }) {
  const doi = findDoi(item);
  const year = findYear(item);
  const venue = item.provider || item.source_kind || item.ecosystem_category;
  return (
    <article className="result-card research-card">
      <div className="badge-row">
        <span className="source-badge">Academic Metadata</span>
        <span className="source-badge muted">{portalLabel(item)}</span>
      </div>
      <h4>{item.title || "Publication"}</h4>
      <div className="card-meta">
        {year && <span className="meta-chip">{year}</span>}
        {venue && <span className="meta-chip">{venue}</span>}
        {doi && <span className="meta-chip">DOI {doi}</span>}
      </div>
      {(item.why_it_matched || item.definition || item.data_source) && (
        <p className="card-def">{item.why_it_matched || item.definition || item.data_source}</p>
      )}
      <div className="card-actions">
        <button type="button" className="card-action-btn" onClick={onViewEvidence}>View metadata</button>
        {item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer" className="card-action-link">Open publication</a>}
      </div>
    </article>
  );
}

function MetricRow({ item }: { item: ConnectorMetricResult }) {
  return (
    <article className="codebook-row">
      <div>
        <strong>{item.metric_name || item.title || "Metric"}</strong>
        {item.metric_description && <p>{item.metric_description}</p>}
      </div>
      <div className="codebook-row-meta">
        {item.dataset_name && <span>{item.dataset_name}</span>}
        <span>{portalLabel(item)}</span>
        {item.category && <span>{item.category}</span>}
        {item.retrieved_at && <span>{formatShortDate(item.retrieved_at)}</span>}
      </div>
    </article>
  );
}

function findDoi(item: ConnectorDatasetResult): string | undefined {
  const text = `${item.source_url || ""} ${item.title || ""}`;
  const match = text.match(/10\.\d{4,9}\/[^\s]+/i);
  return match?.[0];
}

function findYear(item: ConnectorDatasetResult): string | undefined {
  const text = `${item.title || ""} ${item.retrieved_at || ""} ${item.last_modified || ""}`;
  return text.match(/\b(?:19|20)\d{2}\b/)?.[0];
}

function formatShortDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 10);
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
