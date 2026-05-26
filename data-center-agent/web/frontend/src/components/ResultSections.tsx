import type { ChatResponse } from "../types";
import type { DrawerItem } from "./DetailDrawer";
import { OrganizationCard } from "./cards/OrganizationCard";
import { ReportCard } from "./cards/ReportCard";
import { SourceCard } from "./cards/SourceCard";
import { VariableCard } from "./cards/VariableCard";

type Props = {
  results: ChatResponse["results"];
  limitations: string[];
  onViewEvidence: (item: DrawerItem) => void;
  onAuthRequired?: () => void;
  /** When set, cards save directly to this project without a picker */
  projectId?: string;
  /** Called after any card item is saved */
  onItemSaved?: () => void;
};

export function ResultSections({ results, limitations, onViewEvidence, onAuthRequired, projectId, onItemSaved }: Props) {
  const comparison = results.comparison || {};
  const hasComparison = Object.keys(comparison).length > 0;

  const definitionDifferences = Array.isArray(comparison.definition_differences)
    ? (comparison.definition_differences as { raw_variable_name?: string; definition?: string }[])
    : [];

  const totalResults = results.closest_variables.length
    + results.relevant_reports.length
    + results.relevant_organizations.length
    + results.source_links.length;
  if (totalResults === 0 && !hasComparison) return null;

  return (
    <div className="result-groups">
      {results.closest_variables.length > 0 && (
        <details className="result-group" open>
          <summary>Closest Variables <span>{results.closest_variables.length}</span></summary>
          <div className="card-grid">
            {results.closest_variables.map((item, index) => (
              <VariableCard
                key={`${item.title}-${index}`}
                variable={item}
                onViewEvidence={() => onViewEvidence({ kind: "variable", data: item })}
                onAuthRequired={onAuthRequired}
                projectId={projectId}
                onSaved={onItemSaved}
              />
            ))}
          </div>
        </details>
      )}

      {results.relevant_reports.length > 0 && (
        <details className="result-group">
          <summary>Relevant Reports <span>{results.relevant_reports.length}</span></summary>
          <div className="card-grid">
            {results.relevant_reports.map((item, index) => (
              <ReportCard
                key={`${item.title}-${index}`}
                report={item}
                onViewEvidence={() => onViewEvidence({ kind: "report", data: item })}
                onAuthRequired={onAuthRequired}
                projectId={projectId}
                onSaved={onItemSaved}
              />
            ))}
          </div>
        </details>
      )}

      {results.relevant_organizations.length > 0 && (
        <details className="result-group">
          <summary>Organizations <span>{results.relevant_organizations.length}</span></summary>
          <div className="card-grid">
            {results.relevant_organizations.map((item, index) => (
              <OrganizationCard
                key={`${item.name}-${index}`}
                organization={item}
                onViewEvidence={() => onViewEvidence({ kind: "organization", data: item })}
                onAuthRequired={onAuthRequired}
                projectId={projectId}
                onSaved={onItemSaved}
              />
            ))}
          </div>
        </details>
      )}

      {results.source_links.length > 0 && (
        <details className="result-group">
          <summary>Source Links <span>{results.source_links.length}</span></summary>
          <div className="card-grid compact">
            {results.source_links.map((item, index) => (
              <SourceCard
                key={`${item.source_url}-${index}`}
                source={item}
                onViewEvidence={() => onViewEvidence({ kind: "source", data: item })}
                onAuthRequired={onAuthRequired}
                projectId={projectId}
                onSaved={onItemSaved}
              />
            ))}
          </div>
        </details>
      )}

      {hasComparison && (
        <details className="result-group">
          <summary>Comparison <span>1</span></summary>
          <div className="comparison-block">
            <p>{String(comparison.summary ?? "Comparison available.")}</p>
            <dl>
              <dt>Comparability</dt>
              <dd>{String(comparison.comparability ?? "unknown")}</dd>
            </dl>
            {definitionDifferences.length > 0 && (
              <ul>
                {definitionDifferences.slice(0, 5).map((item, index) => (
                  <li key={index}>
                    <strong>{item.raw_variable_name ?? "Variable"}:</strong>{" "}
                    {item.definition ?? "No definition available"}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </details>
      )}

      {limitations.length > 0 && (
        <details className="result-group limitations-group">
          <summary>Limitations <span>{limitations.length}</span></summary>
          <div className="limitations-inline">
            <ul>
              {limitations.map((item, i) => <li key={i}>{item}</li>)}
            </ul>
          </div>
        </details>
      )}
    </div>
  );
}
