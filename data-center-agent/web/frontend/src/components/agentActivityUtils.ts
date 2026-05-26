import type { AgentEvent } from "../types";

export function loadingPlaceholderSequence(): AgentEvent[] {
  const now = new Date().toISOString();
  return [
    {
      id: "placeholder-planning",
      timestamp: now,
      type: "planning",
      status: "pending",
      label: "Planning query",
      detail: "Analyzing your question and selecting data tools",
    },
    {
      id: "placeholder-select",
      timestamp: now,
      type: "planning",
      status: "pending",
      label: "Selecting data tools",
      detail: "Choosing safe search tools for this question",
    },
    {
      id: "placeholder-tool-start",
      timestamp: now,
      type: "tool_start",
      status: "pending",
      label: "Calling data tools",
      detail: "Searching variables, reports, sources, and organizations",
    },
    {
      id: "placeholder-retrieve",
      timestamp: now,
      type: "tool_progress",
      status: "pending",
      label: "Retrieving matches",
      detail: "Loading structured variables, reports, and sources",
    },
    {
      id: "placeholder-rank",
      timestamp: now,
      type: "tool_progress",
      status: "pending",
      label: "Ranking evidence-backed results",
      detail: "Prioritizing the strongest matches",
    },
    {
      id: "placeholder-answer",
      timestamp: now,
      type: "answer_generation",
      status: "pending",
      label: "Generating answer summary",
      detail: "Synthesizing evidence-backed response",
    },
  ];
}

/** @deprecated use loadingPlaceholderSequence */
export function loadingPlaceholderEvents(): AgentEvent[] {
  return loadingPlaceholderSequence();
}

export function decorateProgressiveSteps(events: AgentEvent[], stillRunning: boolean): AgentEvent[] {
  if (events.length === 0) return [];
  return events.map((event, index) => {
    const isLast = index === events.length - 1;
    if (event.status === "failed") return event;
    if (!isLast) return { ...event, status: "completed" as const };
    return { ...event, status: stillRunning ? ("running" as const) : ("completed" as const) };
  });
}

export function buildTimelineSummary(events: AgentEvent[], inProgress = false): string {
  if (events.length === 0) return "Agent activity";

  const completedTools = events.filter(event => event.type === "tool_complete" && event.status === "completed");
  const failed = events.some(event => event.status === "failed");
  const running = inProgress || events.some(event => event.status === "running");

  const runningStep = [...events].reverse().find(event => event.status === "running");

  const toolBit = running
    ? runningStep?.label || "running"
    : completedTools.length > 0
      ? completedTools[completedTools.length - 1].tool_name
        ? `${completedTools[completedTools.length - 1].tool_name} completed`
        : completedTools[completedTools.length - 1].label
      : failed
        ? "failed"
        : `${events.length} steps`;

  const totals = events.reduce(
    (acc, event) => {
      const meta = event.metadata || {};
      acc.variables += meta.variable_count || 0;
      acc.reports += meta.report_count || 0;
      acc.sources += meta.source_count || 0;
      acc.orgs += meta.organization_count || 0;
      return acc;
    },
    { variables: 0, reports: 0, sources: 0, orgs: 0 },
  );

  const countParts = [
    totals.variables ? `${totals.variables} variable${totals.variables !== 1 ? "s" : ""}` : "",
    totals.reports ? `${totals.reports} report${totals.reports !== 1 ? "s" : ""}` : "",
    totals.sources ? `${totals.sources} source${totals.sources !== 1 ? "s" : ""}` : "",
    totals.orgs ? `${totals.orgs} org${totals.orgs !== 1 ? "s" : ""}` : "",
  ].filter(Boolean);

  if (running) return `Agent activity · ${toolBit}…`;
  if (countParts.length > 0) return `Agent activity · ${toolBit} · ${countParts.join(", ")}`;
  return `Agent activity · ${toolBit} · ${events.length} step${events.length !== 1 ? "s" : ""}`;
}

export const LOADING_STEP_MS = 950;
