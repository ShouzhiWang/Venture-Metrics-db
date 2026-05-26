import { useEffect, useState } from "react";
import { getProject } from "../api";
import type { ChatResponse, ProjectItem } from "../types";
import type { DrawerItem } from "./DetailDrawer";
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

  const total = response ? countStructuredResults(response.results) : 0;
  const hasActiveMessage = Boolean(turn && !loading && response);

  return (
    <aside className="evidence-panel" aria-label="Evidence and results">
      <div className="evidence-panel-body">
        <header className="evidence-panel-head">
          <h2>Evidence &amp; Results</h2>
          {turn?.query && hasActiveMessage && (
            <span className="evidence-query-pill">{turn.query}</span>
          )}
        </header>

        {!turn && !activeProject && (
          <p className="evidence-guidance">
            Select a result to inspect evidence, source links, and availability.
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

        {hasActiveMessage && response?.type === "clarification" && (
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

        {hasActiveMessage && response && (response.type === "answer" || response.type === "no_results") && evidenceItem && (
          <SelectedEvidenceDetail
            item={evidenceItem}
            projectId={projectId}
            onAuthRequired={onAuthRequired}
            onSaved={handleSaved}
            onClear={onClearEvidence}
          />
        )}

        {hasActiveMessage && response && (response.type === "answer" || response.type === "no_results") && !evidenceItem && total > 0 && (
          <ActiveMessageResults
            response={response}
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

function ActiveMessageResults({
  response,
  turnQuery,
  projectId,
  onViewEvidence,
  onAuthRequired,
  onSaved,
}: {
  response: ChatResponse;
  turnQuery?: string;
  projectId?: string;
  onViewEvidence: (item: DrawerItem) => void;
  onAuthRequired?: () => void;
  onSaved: () => void;
}) {
  const r = response.results;
  const counts = [
    r.closest_variables.length ? `${r.closest_variables.length} variables` : null,
    r.relevant_reports.length ? `${r.relevant_reports.length} reports` : null,
    r.relevant_organizations.length ? `${r.relevant_organizations.length} orgs` : null,
    r.source_links.length ? `${r.source_links.length} sources` : null,
  ].filter(Boolean);

  return (
    <div className="evidence-context-block">
      <p className="evidence-count-sentence">{counts.join(" · ") || "Results available"}</p>
      <p className="evidence-hint-inline">Select an item to inspect full evidence.</p>

      {r.closest_variables.length > 0 && (
        <ResultSection
          title="Top variables"
          items={r.closest_variables.slice(0, 3).map(v => ({
            key: v.title || v.raw_variable_name || "Variable",
            label: v.title || v.raw_variable_name || "Variable",
            meta: v.data_source || v.geographic_coverage,
            drawer: { kind: "variable" as const, data: v },
          }))}
          onPick={onViewEvidence}
        />
      )}

      {r.relevant_reports.length > 0 && (
        <ResultSection
          title="Top reports"
          items={r.relevant_reports.slice(0, 3).map(rep => ({
            key: rep.title || "Report",
            label: rep.title || "Report",
            meta: [rep.publisher, rep.report_year].filter(Boolean).join(" · "),
            drawer: { kind: "report" as const, data: rep },
          }))}
          onPick={onViewEvidence}
        />
      )}

      {r.source_links.length > 0 && (
        <ResultSection
          title="Top sources"
          items={r.source_links.slice(0, 3).map(src => ({
            key: src.source_url || src.title || "Source",
            label: src.title || src.source_url || "Source",
            meta: src.availability,
            drawer: { kind: "source" as const, data: src },
          }))}
          onPick={onViewEvidence}
        />
      )}

      {r.relevant_organizations.length > 0 && (
        <ResultSection
          title="Organizations"
          items={r.relevant_organizations.slice(0, 2).map(org => ({
            key: org.name || org.title || "Organization",
            label: org.name || org.title || "Organization",
            meta: org.geography,
            drawer: { kind: "organization" as const, data: org },
          }))}
          onPick={onViewEvidence}
        />
      )}

      <div className="evidence-panel-save">
        <SaveToProjectButton
          label="Save result"
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
    </div>
  );
}

function ResultSection({
  title,
  items,
  onPick,
}: {
  title: string;
  items: { key: string; label: string; meta?: string; drawer: DrawerItem }[];
  onPick: (item: DrawerItem) => void;
}) {
  return (
    <section className="evidence-result-section">
      <h3 className="evidence-result-section-title">{title}</h3>
      <ul className="evidence-result-list">
        {items.map(item => (
          <li key={item.key}>
            <button type="button" className="evidence-result-row" onClick={() => onPick(item.drawer)}>
              <strong>{item.label}</strong>
              {item.meta && <span>{item.meta}</span>}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
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

function countStructuredResults(results: ChatResponse["results"]) {
  return (
    results.closest_variables.length +
    results.relevant_reports.length +
    results.relevant_organizations.length +
    results.source_links.length
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
