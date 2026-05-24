import type { VariableResult } from "../../types";
import { AvailabilityBadge } from "./AvailabilityBadge";
import { EvidenceBlock } from "./EvidenceBlock";

type Props = {
  variable: VariableResult;
};

export function VariableCard({ variable }: Props) {
  return (
    <article className="result-card">
      <div className="card-head">
        <h4>{variable.title || variable.raw_variable_name || "Variable"}</h4>
        <AvailabilityBadge value={variable.availability} />
      </div>
      {variable.definition && <p>{variable.definition}</p>}
      <dl className="meta-grid">
        {variable.measurement_method && <><dt>Measurement</dt><dd>{variable.measurement_method}</dd></>}
        {variable.data_source && <><dt>Data source</dt><dd>{variable.data_source}</dd></>}
        {variable.geographic_coverage && <><dt>Geography</dt><dd>{variable.geographic_coverage}</dd></>}
        {variable.temporal_coverage && <><dt>Time</dt><dd>{variable.temporal_coverage}</dd></>}
      </dl>
      <EvidenceBlock quote={variable.evidence_quote} />
      {variable.source_url && <a href={variable.source_url} target="_blank" rel="noreferrer">Open source</a>}
    </article>
  );
}
