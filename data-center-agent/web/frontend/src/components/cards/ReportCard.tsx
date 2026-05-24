import type { ReportResult } from "../../types";

type Props = {
  report: ReportResult;
};

export function ReportCard({ report }: Props) {
  return (
    <article className="result-card">
      <h4>{report.title || "Report"}</h4>
      <dl className="meta-grid">
        {report.publisher && <><dt>Publisher</dt><dd>{report.publisher}</dd></>}
        {report.report_year && <><dt>Year</dt><dd>{report.report_year}</dd></>}
        {(report.geography || report.geographic_coverage) && <><dt>Geography</dt><dd>{report.geography || report.geographic_coverage}</dd></>}
      </dl>
      {report.why_it_matched && <p>{report.why_it_matched}</p>}
      {report.matched_variables && report.matched_variables.length > 0 && (
        <p>Matched variables: {report.matched_variables.map((item) => item.raw_variable_name || item.title).filter(Boolean).join(", ")}</p>
      )}
      {report.source_url && <a href={report.source_url} target="_blank" rel="noreferrer">Open source</a>}
    </article>
  );
}
