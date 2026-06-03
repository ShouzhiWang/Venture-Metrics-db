import { X } from "lucide-react";
import type { VariableResult, ReportResult, OrganizationResult, SourceLink } from "../types";
import { AvailabilityBadge } from "./cards/AvailabilityBadge";

export type DrawerItem =
  | { kind: "variable"; data: VariableResult }
  | { kind: "report"; data: ReportResult }
  | { kind: "organization"; data: OrganizationResult }
  | { kind: "source"; data: SourceLink };

type Props = {
  item: DrawerItem | null;
  onClose: () => void;
};

export function DetailDrawer({ item, onClose }: Props) {
  if (!item) return null;

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
      <aside className="drawer" role="complementary" aria-label="Detail view">
        <div className="drawer-header">
          <span className="drawer-title">{getTitle(item)}</span>
          <button className="drawer-close" onClick={onClose} aria-label="Close detail view">
            <X size={14} aria-hidden="true" />
          </button>
        </div>
        <div className="drawer-body">
          {item.kind === "variable" && <VariableDetail data={item.data} />}
          {item.kind === "report" && <ReportDetail data={item.data} />}
          {item.kind === "organization" && <OrgDetail data={item.data} />}
          {item.kind === "source" && <SourceDetail data={item.data} />}
        </div>
      </aside>
    </>
  );
}

function getTitle(item: DrawerItem): string {
  switch (item.kind) {
    case "variable": return item.data.title || item.data.raw_variable_name || "Variable";
    case "report": return item.data.title || "Report";
    case "organization": return item.data.name || item.data.title || "Organization";
    case "source": return item.data.title || "Source";
  }
}

function Field({ label, value }: { label: string; value?: string | number | null }) {
  if (!value) return null;
  return (
    <div className="drawer-field">
      <span className="drawer-label">{label}</span>
      <span className="drawer-value">{String(value)}</span>
    </div>
  );
}

function LinkField({ label, href }: { label: string; href?: string | null }) {
  if (!href) return null;
  return (
    <div className="drawer-field">
      <span className="drawer-label">{label}</span>
      <span className="drawer-value">
        <a href={href} target="_blank" rel="noreferrer">{href}</a>
      </span>
    </div>
  );
}

function VariableDetail({ data }: { data: VariableResult }) {
  return (
    <>
      {data.availability && (
        <div className="drawer-field">
          <span className="drawer-label">Availability</span>
          <div style={{ marginTop: 4 }}>
            <AvailabilityBadge value={data.availability} />
          </div>
        </div>
      )}
      <Field label="Definition" value={data.definition} />
      <Field label="Measurement method" value={data.measurement_method} />
      <Field label="Data source" value={data.data_source} />
      <Field label="Geography" value={data.geographic_coverage} />
      <Field label="Time coverage" value={data.temporal_coverage} />
      <Field label="Confidence" value={typeof data.confidence_score === "number" ? data.confidence_score.toFixed(2) : undefined} />
      <Field label="Review status" value={data.review_status} />
      <Field label="Page" value={data.page_number} />
      <Field label="Source report" value={data.source_report_title} />
      {data.evidence_quote && (
        <div className="drawer-field">
          <span className="drawer-label">Evidence</span>
          <blockquote className="drawer-evidence">{data.evidence_quote}</blockquote>
        </div>
      )}
      <LinkField label="Source URL" href={data.source_url} />
      {data.local_path && <Field label="Local file" value={data.local_path} />}
    </>
  );
}

function ReportDetail({ data }: { data: ReportResult }) {
  return (
    <>
      <Field label="Publisher" value={data.publisher} />
      <Field label="Source organization" value={data.source_organization} />
      <Field label="Year" value={data.report_year} />
      <Field label="Geography" value={data.geography || data.geographic_coverage} />
      <Field label="Summary" value={data.summary} />
      {data.why_it_matched && (
        <div className="drawer-field">
          <span className="drawer-label">Why it matched</span>
          <blockquote className="drawer-evidence">{data.why_it_matched}</blockquote>
        </div>
      )}
      {data.matched_variables && data.matched_variables.length > 0 && (
        <div className="drawer-field">
          <span className="drawer-label">Matched variables</span>
          <span className="drawer-value">
            {data.matched_variables.map(v => v.raw_variable_name || v.title).filter(Boolean).join(", ")}
          </span>
        </div>
      )}
      {data.chunks && data.chunks.length > 0 && (
        <div className="drawer-field">
          <span className="drawer-label">Relevant chunks</span>
          <span className="drawer-value">
            {data.chunks.map(chunk => chunk.title || chunk.evidence_quote || chunk.why_it_matched).filter(Boolean).slice(0, 4).join(" | ")}
          </span>
        </div>
      )}
      <LinkField label="Source URL" href={data.source_url} />
      {data.local_path && <Field label="Local file" value={data.local_path} />}
    </>
  );
}

function OrgDetail({ data }: { data: OrganizationResult }) {
  return (
    <>
      <Field label="Type" value={data.organization_type} />
      <Field label="Geography" value={data.geography} />
      <Field label="Description" value={data.description} />
      <LinkField label="Website" href={data.website_url || data.source_url} />
    </>
  );
}

function SourceDetail({ data }: { data: SourceLink }) {
  return (
    <>
      <Field label="Result type" value={data.object_type || data.connector_type || data.source_type} />
      <Field label="Connector" value={data.connector_name} />
      {data.availability && (
        <div className="drawer-field">
          <span className="drawer-label">Availability</span>
          <div style={{ marginTop: 4 }}>
            <AvailabilityBadge value={data.availability} />
          </div>
        </div>
      )}
      <Field label="Score" value={typeof data.score === "number" ? data.score.toFixed(3) : undefined} />
      <Field label="Page" value={data.page_number} />
      {data.why_it_matched && (
        <div className="drawer-field">
          <span className="drawer-label">Why it matched</span>
          <blockquote className="drawer-evidence">{data.why_it_matched}</blockquote>
        </div>
      )}
      {data.evidence_quote && (
        <div className="drawer-field">
          <span className="drawer-label">Evidence</span>
          <blockquote className="drawer-evidence">{data.evidence_quote}</blockquote>
        </div>
      )}
      <LinkField label="Source URL" href={data.source_url} />
      {data.local_path && <Field label="Local file" value={data.local_path} />}
    </>
  );
}
