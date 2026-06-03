import type { VariableResult } from "../../types";
import { SaveToProjectButton } from "../SaveToProjectButton";
import { AvailabilityBadge } from "./AvailabilityBadge";

type Props = {
  variable: VariableResult;
  onViewEvidence: () => void;
  onAuthRequired?: () => void;
  projectId?: string;
  onSaved?: () => void;
};

export function VariableCard({ variable, onViewEvidence, onAuthRequired, projectId, onSaved }: Props) {
  const name = variable.title || variable.raw_variable_name || "Variable";
  const id = variable.id || variable.object_id || variable.variable_id;

  return (
    <article className="result-card">
      <div className="card-head">
        <h4>{name}</h4>
        <AvailabilityBadge value={variable.availability} />
      </div>

      {variable.definition && (
        <p className="card-def">{variable.definition}</p>
      )}

      <div className="card-meta">
        <span className="meta-chip">Report Variable</span>
        {variable.data_source && (
          <span className="meta-chip">{variable.data_source}</span>
        )}
        {variable.geographic_coverage && (
          <span className="meta-chip">{variable.geographic_coverage}</span>
        )}
        {variable.temporal_coverage && (
          <span className="meta-chip">{variable.temporal_coverage}</span>
        )}
        {typeof variable.confidence_score === "number" && (
          <span className="meta-chip">Confidence {Math.round(variable.confidence_score * 100)}%</span>
        )}
        {variable.review_status && (
          <span className="meta-chip">{variable.review_status}</span>
        )}
        {variable.page_number && (
          <span className="meta-chip">Page {variable.page_number}</span>
        )}
      </div>

      {(variable.measurement_method || variable.evidence_quote || variable.source_report_title) && (
        <dl className="variable-facts">
          {variable.measurement_method && (
            <>
              <dt>Measurement</dt>
              <dd>{variable.measurement_method}</dd>
            </>
          )}
          {variable.source_report_title && (
            <>
              <dt>Report</dt>
              <dd>{variable.source_report_title}</dd>
            </>
          )}
          {variable.evidence_quote && (
            <>
              <dt>Evidence</dt>
              <dd>{variable.evidence_quote}</dd>
            </>
          )}
        </dl>
      )}

      <div className="card-actions">
        <button
          type="button"
          className="card-action-btn"
          onClick={onViewEvidence}
        >
          View evidence
        </button>
        {variable.source_url && (
          <a
            href={variable.source_url}
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
            item_type: "variable",
            item_id: id,
            title: name,
            metadata: { variable },
          }}
        />
      </div>
    </article>
  );
}
