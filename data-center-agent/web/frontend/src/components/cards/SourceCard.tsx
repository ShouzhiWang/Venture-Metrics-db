import type { SourceLink } from "../../types";
import { SaveToProjectButton } from "../SaveToProjectButton";
import { AvailabilityBadge } from "./AvailabilityBadge";

type Props = {
  source: SourceLink;
  onViewEvidence: () => void;
  onAuthRequired?: () => void;
};

export function SourceCard({ source, onViewEvidence, onAuthRequired }: Props) {
  const title = source.title || source.source_url || "Source";
  const id = source.id || source.object_id || source.source_id;

  return (
    <article className="result-card">
      <div className="card-head">
        <h4>{title}</h4>
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
        <SaveToProjectButton
          onAuthRequired={onAuthRequired}
          payload={{
            item_type: "source",
            item_id: id,
            title,
            metadata: { source },
          }}
        />
      </div>
    </article>
  );
}
