import { useEffect, useState } from "react";
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
};

const TABS = ["Variables", "Reports", "Organizations", "Sources", "Comparison"] as const;
type TabName = typeof TABS[number];

export function ResultSections({ results, limitations, onViewEvidence, onAuthRequired }: Props) {
  const comparison = results.comparison || {};
  const hasComparison = Object.keys(comparison).length > 0;

  const counts: Record<TabName, number> = {
    Variables: results.closest_variables.length,
    Reports: results.relevant_reports.length,
    Organizations: results.relevant_organizations.length,
    Sources: results.source_links.length,
    Comparison: hasComparison ? 1 : 0,
  };

  const firstWithData = TABS.find(t => counts[t] > 0) ?? "Variables";
  const [active, setActive] = useState<TabName>(firstWithData);

  useEffect(() => {
    setActive(TABS.find(t => counts[t] > 0) ?? "Variables");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results]);

  const definitionDifferences = Array.isArray(comparison.definition_differences)
    ? (comparison.definition_differences as { raw_variable_name?: string; definition?: string }[])
    : [];

  const totalResults = counts.Variables + counts.Reports + counts.Organizations + counts.Sources;
  if (totalResults === 0 && !hasComparison) return null;

  return (
    <div className="result-tabs">
      <div className="tab-bar" role="tablist">
        {TABS.map(tab => {
          const count = counts[tab];
          const isDisabled = count === 0;
          return (
            <button
              key={tab}
              role="tab"
              aria-selected={active === tab}
              className={`tab-btn${active === tab ? " active" : ""}${isDisabled ? " empty" : ""}`}
              onClick={() => !isDisabled && setActive(tab)}
              disabled={isDisabled}
            >
              {tab}
              {count > 0 && <span className="tab-count">{count}</span>}
            </button>
          );
        })}
      </div>

      <div className="tab-content" role="tabpanel">
        {active === "Variables" && results.closest_variables.length > 0 && (
          <div className="card-grid">
            {results.closest_variables.map((item, index) => (
              <VariableCard
                key={`${item.title}-${index}`}
                variable={item}
                onViewEvidence={() => onViewEvidence({ kind: "variable", data: item })}
                onAuthRequired={onAuthRequired}
              />
            ))}
          </div>
        )}

        {active === "Reports" && results.relevant_reports.length > 0 && (
          <div className="card-grid">
            {results.relevant_reports.map((item, index) => (
              <ReportCard
                key={`${item.title}-${index}`}
                report={item}
                onViewEvidence={() => onViewEvidence({ kind: "report", data: item })}
                onAuthRequired={onAuthRequired}
              />
            ))}
          </div>
        )}

        {active === "Organizations" && results.relevant_organizations.length > 0 && (
          <div className="card-grid">
            {results.relevant_organizations.map((item, index) => (
              <OrganizationCard
                key={`${item.name}-${index}`}
                organization={item}
                onViewEvidence={() => onViewEvidence({ kind: "organization", data: item })}
                onAuthRequired={onAuthRequired}
              />
            ))}
          </div>
        )}

        {active === "Sources" && results.source_links.length > 0 && (
          <div className="card-grid compact">
            {results.source_links.map((item, index) => (
              <SourceCard
                key={`${item.source_url}-${index}`}
                source={item}
                onViewEvidence={() => onViewEvidence({ kind: "source", data: item })}
                onAuthRequired={onAuthRequired}
              />
            ))}
          </div>
        )}

        {active === "Comparison" && hasComparison && (
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
        )}

        {limitations.length > 0 && (
          <div className="limitations-inline">
            <ul>
              {limitations.map((item, i) => <li key={i}>{item}</li>)}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
