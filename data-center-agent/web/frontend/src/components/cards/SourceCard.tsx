import type { SourceLink } from "../../types";
import { AvailabilityBadge } from "./AvailabilityBadge";

type Props = {
  source: SourceLink;
};

export function SourceCard({ source }: Props) {
  return (
    <article className="result-card source-card">
      <div className="card-head">
        <h4>{source.title || source.source_url || "Source"}</h4>
        <AvailabilityBadge value={source.availability} />
      </div>
      {source.source_url && <a href={source.source_url} target="_blank" rel="noreferrer">{source.source_url}</a>}
      {source.local_path && <p>{source.local_path}</p>}
    </article>
  );
}
