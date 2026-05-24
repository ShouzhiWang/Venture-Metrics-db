import type { ReportResult } from "../../types";

type Props = {
  report: ReportResult;
  onViewEvidence: () => void;
};

export function ReportCard({ report, onViewEvidence }: Props) {
  const geo = report.geography || report.geographic_coverage;

  return (
    <article className="result-card">
      <h4>{report.title || "Report"}</h4>

      <div className="card-meta">
        {report.publisher && <span className="meta-chip">{report.publisher}</span>}
        {report.report_year && <span className="meta-chip">{report.report_year}</span>}
        {geo && <span className="meta-chip">{geo}</span>}
      </div>

      {report.why_it_matched && (
        <p className="card-def">{report.why_it_matched}</p>
      )}

      <div className="card-actions">
        <button
          type="button"
          className="card-action-btn"
          onClick={onViewEvidence}
        >
          View details
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
      </div>
    </article>
  );
}
