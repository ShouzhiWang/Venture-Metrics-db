import type { OrganizationResult } from "../../types";
import { SaveToProjectButton } from "../SaveToProjectButton";

type Props = {
  organization: OrganizationResult;
  onViewEvidence: () => void;
  onAuthRequired?: () => void;
  projectId?: string;
  onSaved?: () => void;
};

export function OrganizationCard({ organization, onViewEvidence, onAuthRequired, projectId, onSaved }: Props) {
  const url = organization.website_url || organization.source_url;
  const title = organization.name || organization.title || "Organization";
  const id = organization.id || organization.object_id || organization.organization_id;

  return (
    <article className="result-card">
      <h4>{title}</h4>

      <div className="card-meta">
        {organization.organization_type && (
          <span className="meta-chip">{organization.organization_type}</span>
        )}
        {organization.geography && (
          <span className="meta-chip">{organization.geography}</span>
        )}
      </div>

      {organization.description && (
        <p className="card-def">{organization.description}</p>
      )}

      <div className="card-actions">
        <button
          type="button"
          className="card-action-btn"
          onClick={onViewEvidence}
        >
          View details
        </button>
        {url && (
          <a href={url} target="_blank" rel="noreferrer" className="card-action-link">
            Open website
          </a>
        )}
        <SaveToProjectButton
          onAuthRequired={onAuthRequired}
          onSaved={onSaved}
          projectId={projectId}
          payload={{
            item_type: "organization",
            item_id: id,
            title,
            metadata: { organization },
          }}
        />
      </div>
    </article>
  );
}
