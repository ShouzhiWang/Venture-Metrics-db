import type { SourceLink } from "../../types";
import { AvailabilityBadge } from "./AvailabilityBadge";

type Props = {
  source: SourceLink;
  onViewEvidence: () => void;
};

export function SourceCard({ source, onViewEvidence }: Props) {
  return (
    <article className="result-card">
      <div className="card-head">
        <h4>{source.title || source.source_url || "Source"}</h4>
        <AvailabilityBadge value={source.availability} />
      </div>

      <div className="card-actions">
        <button
          type="button"
          className="card-action-btn"
          onClick={onViewEvidence}
        >
          View details
        </button>
        {source.source_url && (
          <a
            href={source.source_url}
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
