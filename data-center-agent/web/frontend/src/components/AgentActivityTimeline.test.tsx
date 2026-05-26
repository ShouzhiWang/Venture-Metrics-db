/** @vitest-environment jsdom */
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentActivityTimeline } from "./AgentActivityTimeline";
import { buildTimelineSummary, decorateProgressiveSteps } from "./agentActivityUtils";
import type { AgentEvent } from "../types";

const completedEvents: AgentEvent[] = [
  {
    id: "1",
    timestamp: "2026-01-01T00:00:00Z",
    type: "planning",
    status: "completed",
    label: "Query planned",
    detail: "Query planner classified intent: find_data",
    metadata: { intent: "find_data" },
  },
  {
    id: "2",
    timestamp: "2026-01-01T00:00:01Z",
    type: "tool_complete",
    status: "completed",
    label: "find_data completed",
    detail: "Retrieved 5 variables, 2 reports, 1 source",
    tool_name: "find_data",
    metadata: { variable_count: 5, report_count: 2, source_count: 1 },
  },
];

describe("AgentActivityTimeline", () => {
  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });

  it("renders collapsed summary with counts", () => {
    render(<AgentActivityTimeline events={completedEvents} defaultCollapsed />);
    expect(screen.getByText(/Agent activity · find_data completed · 5 variables, 2 reports, 1 source/)).toBeTruthy();
  });

  it("renders running and failed states when expanded", () => {
    const events: AgentEvent[] = [
      ...completedEvents,
      {
        id: "3",
        timestamp: "2026-01-01T00:00:02Z",
        type: "error",
        status: "failed",
        label: "compare_concepts_auto failed",
        detail: "Not enough comparable reports",
        tool_name: "compare_concepts_auto",
      },
    ];
    render(<AgentActivityTimeline events={events} defaultCollapsed={false} />);
    expect(screen.getByText("compare_concepts_auto failed")).toBeTruthy();
  });

  it("shows live backend events during loading without placeholders", () => {
    const liveEvents: AgentEvent[] = [
      {
        id: "live-1",
        timestamp: "2026-01-01T00:00:00Z",
        type: "planning",
        status: "completed",
        label: "Query planned",
        detail: "Query planner classified intent: find_data",
      },
      {
        id: "live-2",
        timestamp: "2026-01-01T00:00:01Z",
        type: "tool_start",
        status: "running",
        label: "Calling find_data",
        detail: "Searching variables, reports, sources, and organizations",
        tool_name: "find_data",
      },
    ];
    render(<AgentActivityTimeline events={liveEvents} isLoading defaultCollapsed={false} />);
    expect(screen.getByText("Query planned")).toBeTruthy();
    expect(screen.getByText("Calling find_data")).toBeTruthy();
    expect(screen.queryByText("Selecting data tools")).toBeNull();
  });

  it("reveals placeholder steps over time while loading", () => {
    vi.useFakeTimers();
    render(<AgentActivityTimeline isLoading defaultCollapsed={false} />);
    expect(screen.getByText("Planning query")).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByText("Selecting data tools")).toBeTruthy();
    expect(screen.queryByText("Calling data tools")).toBeNull();
  });

  it("shows all backend events immediately after completion", () => {
    const manyEvents: AgentEvent[] = Array.from({ length: 4 }, (_, index) => ({
      id: `step-${index}`,
      timestamp: "2026-01-01T00:00:00Z",
      type: "planning",
      status: "completed",
      label: `Step ${index + 1}`,
      detail: `Detail ${index + 1}`,
    }));

    render(<AgentActivityTimeline events={manyEvents} defaultCollapsed={false} isLoading={false} />);
    expect(screen.getByText("Step 1")).toBeTruthy();
    expect(screen.getByText("Step 4")).toBeTruthy();
  });
});

describe("decorateProgressiveSteps", () => {
  it("marks prior steps completed and only the last as running", () => {
    const steps = decorateProgressiveSteps(
      [
        { id: "1", timestamp: "", type: "planning", status: "pending", label: "A", detail: "" },
        { id: "2", timestamp: "", type: "tool_start", status: "pending", label: "B", detail: "" },
      ],
      true,
    );
    expect(steps[0].status).toBe("completed");
    expect(steps[1].status).toBe("running");
  });
});

describe("buildTimelineSummary", () => {
  it("includes step count when no result counts exist", () => {
    const summary = buildTimelineSummary([
      {
        id: "1",
        timestamp: "2026-01-01T00:00:00Z",
        type: "planning",
        status: "completed",
        label: "Query planned",
        detail: "",
      },
    ]);
    expect(summary).toContain("1 step");
  });

  it("shows running label while in progress", () => {
    const summary = buildTimelineSummary(
      [{ id: "1", timestamp: "", type: "planning", status: "running", label: "Planning query", detail: "" }],
      true,
    );
    expect(summary).toContain("Planning query");
    expect(summary).toContain("…");
  });
});
