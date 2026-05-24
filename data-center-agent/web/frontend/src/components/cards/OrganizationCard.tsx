import type { OrganizationResult } from "../../types";

type Props = {
  organization: OrganizationResult;
  onViewEvidence: () => void;
};

export function OrganizationCard({ organization, onViewEvidence }: Props) {
  const url = organization.website_url || organization.source_url;

  return (
    <article className="result-card">
      <h4>{organization.name || organization.title || "Organization"}</h4>

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
      </div>
    </article>
  );
}
