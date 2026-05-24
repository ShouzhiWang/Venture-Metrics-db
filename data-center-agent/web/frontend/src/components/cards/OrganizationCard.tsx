import type { OrganizationResult } from "../../types";

type Props = {
  organization: OrganizationResult;
};

export function OrganizationCard({ organization }: Props) {
  return (
    <article className="result-card">
      <h4>{organization.name || organization.title || "Organization"}</h4>
      <dl className="meta-grid">
        {organization.organization_type && <><dt>Type</dt><dd>{organization.organization_type}</dd></>}
        {organization.geography && <><dt>Geography</dt><dd>{organization.geography}</dd></>}
      </dl>
      {organization.description && <p>{organization.description}</p>}
      {(organization.website_url || organization.source_url) && (
        <a href={organization.website_url || organization.source_url} target="_blank" rel="noreferrer">Open website</a>
      )}
    </article>
  );
}
