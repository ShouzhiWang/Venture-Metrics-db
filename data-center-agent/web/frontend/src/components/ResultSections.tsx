import type { ChatResponse } from "../types";
import { OrganizationCard } from "./cards/OrganizationCard";
import { ReportCard } from "./cards/ReportCard";
import { SourceCard } from "./cards/SourceCard";
import { VariableCard } from "./cards/VariableCard";

type Props = {
  results: ChatResponse["results"];
  limitations: string[];
};

export function ResultSections({ results, limitations }: Props) {
  const comparison = results.comparison || {};
  const hasComparison = Object.keys(comparison).length > 0;
  const definitionDifferences = Array.isArray(comparison.definition_differences)
    ? comparison.definition_differences
    : [];
  return (
    <div className="sections-grid">
      {results.closest_variables.length > 0 && (
        <section className="section-block">
          <h3>Closest Variables</h3>
          <div className="card-list">
            {results.closest_variables.map((item, index) => <VariableCard key={`${item.title}-${index}`} variable={item} />)}
          </div>
        </section>
      )}

      {results.relevant_reports.length > 0 && (
        <section className="section-block">
          <h3>Relevant Reports</h3>
          <div className="card-list">
            {results.relevant_reports.map((item, index) => <ReportCard key={`${item.title}-${index}`} report={item} />)}
          </div>
        </section>
      )}

      {results.relevant_organizations.length > 0 && (
        <section className="section-block">
          <h3>Organizations</h3>
          <div className="card-list">
            {results.relevant_organizations.map((item, index) => <OrganizationCard key={`${item.name}-${index}`} organization={item} />)}
          </div>
        </section>
      )}

      {results.source_links.length > 0 && (
        <section className="section-block">
          <h3>Source Links</h3>
          <div className="card-list compact">
            {results.source_links.map((item, index) => <SourceCard key={`${item.source_url}-${index}`} source={item} />)}
          </div>
        </section>
      )}

      {hasComparison && (
        <section className="section-block">
          <h3>Concept Comparison</h3>
          <div className="comparison-box">
            <p>{String(comparison.summary || "Comparison available.")}</p>
            <dl>
              <dt>Comparability</dt>
              <dd>{String(comparison.comparability || "unknown")}</dd>
            </dl>
            {definitionDifferences.length > 0 && (
              <ul>
                {definitionDifferences.slice(0, 5).map((item: any, index: number) => (
                  <li key={index}>
                    <strong>{item.raw_variable_name || "Variable"}:</strong> {item.definition || "No definition available"}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      )}

      {limitations.length > 0 && (
        <section className="section-block">
          <h3>Limitations</h3>
          <ul className="plain-list">
            {limitations.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </section>
      )}
    </div>
  );
}
