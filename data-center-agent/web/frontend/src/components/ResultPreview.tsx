import type {
  ChatResponse,
  OrganizationResult,
  ReportResult,
  SourceLink,
  VariableResult,
} from "../types";
import type { DrawerItem } from "./DetailDrawer";
import { SaveToProjectButton } from "./SaveToProjectButton";
import { AvailabilityBadge } from "./cards/AvailabilityBadge";

export type PreviewUnion =
  | { kind: "variable"; data: VariableResult }
  | { kind: "report"; data: ReportResult }
  | { kind: "organization"; data: OrganizationResult }
  | { kind: "source"; data: SourceLink };

export function pickResultPreviews(results: ChatResponse["results"], limit = 3): PreviewUnion[] {
  const picked: PreviewUnion[] = [];
  for (const v of results.closest_variables) {
    picked.push({ kind: "variable", data: v });
    if (picked.length >= limit) return picked;
  }
  for (const r of results.relevant_reports) {
    picked.push({ kind: "report", data: r });
    if (picked.length >= limit) return picked;
  }
  for (const o of results.relevant_organizations) {
    picked.push({ kind: "organization", data: o });
    if (picked.length >= limit) return picked;
  }
  for (const s of results.source_links) {
    picked.push({ kind: "source", data: s });
    if (picked.length >= limit) return picked;
  }
  return picked;
}

type PreviewCardProps = {
  item: PreviewUnion;
  answerSummary: string;
  query?: string;
  response: ChatResponse;
  onViewEvidence: (item: DrawerItem) => void;
  onAuthRequired?: () => void;
  projectId?: string;
  onSaved: () => void;
  hideSaveButton?: boolean;
};

export function CompactResultPreview({
  item,
  answerSummary,
  query,
  response,
  onViewEvidence,
  onAuthRequired,
  projectId,
  onSaved,
  hideSaveButton = false,
}: PreviewCardProps) {
  return (
    <article className="result-preview-card">
      <div className="result-preview-head">
        <strong className="result-preview-title">{previewTitle(item)}</strong>
        <span className={`result-preview-type rt-${item.kind}`}>{previewTypeLabel(item.kind)}</span>
        {availabilityFor(item) != null && <AvailabilityBadge value={availabilityFor(item)} />}
      </div>
      {previewSubtitle(item) && <p className="result-preview-line">{previewSubtitle(item)}</p>}
      {previewSourceLine(item) && <p className="result-preview-meta">{previewSourceLine(item)}</p>}
      <div className="result-preview-actions">
        <button type="button" className="result-preview-btn" onClick={() => onViewEvidence(previewDrawerItem(item))}>
          View evidence
        </button>
        {!hideSaveButton && (
          <SaveToProjectButton
            label="Save to project"
            onAuthRequired={onAuthRequired}
            onSaved={onSaved}
            projectId={projectId}
            payload={previewSavePayload(item, answerSummary, query, response)}
          />
        )}
      </div>
    </article>
  );
}

function previewDrawerItem(item: PreviewUnion): DrawerItem {
  if (item.kind === "variable") return { kind: "variable", data: item.data };
  if (item.kind === "report") return { kind: "report", data: item.data };
  if (item.kind === "organization") return { kind: "organization", data: item.data };
  return { kind: "source", data: item.data };
}

function previewTitle(item: PreviewUnion): string {
  if (item.kind === "variable") return item.data.title || item.data.raw_variable_name || "Variable";
  if (item.kind === "report") return item.data.title || "Report";
  if (item.kind === "organization") return item.data.name || item.data.title || "Organization";
  return item.data.title || item.data.source_url || "Source";
}

function previewTypeLabel(kind: PreviewUnion["kind"]): string {
  const map: Record<PreviewUnion["kind"], string> = {
    variable: "Variable",
    report: "Report",
    organization: "Organization",
    source: "Source",
  };
  return map[kind];
}

function availabilityFor(item: PreviewUnion): string | undefined {
  if (item.kind === "variable" || item.kind === "source") return item.data.availability;
  return undefined;
}

function previewSubtitle(item: PreviewUnion): string | undefined {
  const oneLine = (s?: string) => {
    const t = (s || "").trim();
    if (!t) return undefined;
    return t.length > 140 ? `${t.slice(0, 137)}…` : t;
  };

  if (item.kind === "variable") return oneLine(item.data.definition);
  if (item.kind === "report") return oneLine(item.data.why_it_matched || item.data.publisher || undefined);
  if (item.kind === "organization") return oneLine(item.data.description || item.data.organization_type);
  return undefined;
}

function previewSourceLine(item: PreviewUnion): string | undefined {
  if (item.kind === "variable") {
    const ds = item.data.data_source?.trim();
    if (ds) return `Source: ${ds}`;
    const url = item.data.source_url;
    return url ? "Source: linked record" : undefined;
  }
  if (item.kind === "report") {
    const parts = [item.data.publisher, item.data.report_year ? String(item.data.report_year) : ""].filter(Boolean);
    const head = parts.join(" · ");
    return head ? `Report: ${head}` : undefined;
  }
  if (item.kind === "organization") {
    const geo = item.data.geography?.trim();
    const url = item.data.website_url || item.data.source_url;
    if (geo) return `Organization · ${geo}`;
    if (url) return "Organization · web";
    return "Organization";
  }
  const url = item.data.source_url;
  return url ? `Source link · ${truncateUrl(url)}` : undefined;
}

function truncateUrl(url: string) {
  return url.length > 56 ? `${url.slice(0, 53)}…` : url;
}

function previewSavePayload(
  item: PreviewUnion,
  answerSummary: string,
  query: string | undefined,
  response: ChatResponse,
) {
  if (item.kind === "variable") {
    const title = previewTitle(item);
    const id = item.data.id || item.data.object_id || item.data.variable_id;
    return {
      item_type: "variable" as const,
      item_id: id,
      title,
      metadata: {
        variable: item.data,
        query,
        answer_summary: answerSummary,
        saved_from: response.saved_result_id,
      },
    };
  }
  if (item.kind === "report") {
    const title = previewTitle(item);
    const id = item.data.id || item.data.object_id || item.data.report_id;
    return {
      item_type: "report" as const,
      item_id: id,
      title,
      metadata: {
        report: item.data,
        query,
        answer_summary: answerSummary,
        saved_from: response.saved_result_id,
      },
    };
  }
  if (item.kind === "organization") {
    const title = previewTitle(item);
    const id = item.data.id || item.data.object_id || item.data.organization_id;
    return {
      item_type: "organization" as const,
      item_id: id,
      title,
      metadata: {
        organization: item.data,
        query,
        answer_summary: answerSummary,
        saved_from: response.saved_result_id,
      },
    };
  }
  const title = previewTitle(item);
  const id = item.data.id || item.data.object_id || item.data.source_id;
  return {
    item_type: "source" as const,
    item_id: id,
    title,
    metadata: {
      source: item.data,
      query,
      answer_summary: answerSummary,
      saved_from: response.saved_result_id,
    },
  };
}
