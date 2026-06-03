import type { ReportResult } from "../../types";
import { SaveToProjectButton } from "../SaveToProjectButton";

type Props = {
  report: ReportResult;
  onViewEvidence: () => void;
  onAuthRequired?: () => void;
  projectId?: string;
  onSaved?: () => void;
};

export function ReportCard({ report, onViewEvidence, onAuthRequired, projectId, onSaved }: Props) {
  const geo = report.geography || report.geographic_coverage;
  const title = report.title || "Report";
  const id = report.id || report.object_id || report.report_id;

  return (
    <article className="result-card">
      <div className="badge-row">
        <span className="source-badge">Internal DB</span>
        <span className="source-badge muted">Report Reader</span>
      </div>
      <h4>{title}</h4>

      <div className="card-meta">
        {(report.publisher || report.source_organization) && <span className="meta-chip">{report.publisher || report.source_organization}</span>}
        {report.report_year && <span className="meta-chip">{report.report_year}</span>}
        {geo && <span className="meta-chip">{geo}</span>}
        {typeof report.score === "number" && <span className="meta-chip">Score {report.score.toFixed(2)}</span>}
      </div>

      {(report.summary || report.why_it_matched) && (
        <p className="card-def">{report.summary || report.why_it_matched}</p>
      )}

      <div className="card-actions">
        <button
          type="button"
          className="card-action-btn"
          onClick={onViewEvidence}
        >
          View evidence
        </button>
        {report.source_url && (
          <a
            href={report.source_url}
            target="_blank"
            rel="noreferrer"
            className="card-action-link"
          >
            Open source
          </a>
        )}
        <SaveToProjectButton
          onAuthRequired={onAuthRequired}
          onSaved={onSaved}
          projectId={projectId}
          payload={{
            item_type: "report",
            item_id: id,
            title,
            metadata: { report },
          }}
        />
      </div>
    </article>
  );
}
