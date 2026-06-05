/** @vitest-environment jsdom */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EvidenceWorkspacePanel } from "./EvidenceWorkspacePanel";
import type { ChatResponse } from "../types";

vi.mock("../api", () => ({
  getProject: vi.fn(),
  listProjects: vi.fn(),
  addProjectItem: vi.fn(),
  createProject: vi.fn(),
}));

const baseResponse: ChatResponse = {
  type: "answer",
  message: "I created a table in the evidence panel.",
  assistant_message: "I created a table in the evidence panel.",
  intent: "find_data",
  clarifying_questions: [],
  tool_calls: [{ name: "find_data", args: {}, status: "completed" }],
  results: {
    closest_variables: [
      {
        title: "VC deal count",
        definition: "Number of venture capital deals.",
        data_source: "Official startup database",
        evidence_quote: "Deals are counted by announcement date.",
      },
    ],
    relevant_reports: [{ title: "Singapore venture report", publisher: "EnterpriseSG", report_year: 2024 }],
    relevant_organizations: [{ name: "Enterprise Singapore", organization_type: "Agency", geography: "Singapore" }],
    source_links: [{ title: "Methodology note", source_url: "https://example.test/methodology", availability: "internal" }],
    connector_datasets: [
      {
        title: "Startup dataset",
        source_url: "https://data.gov.sg/startups",
        row_count: 120,
        column_count: 8,
        retrieved_at: "2026-06-01T00:00:00Z",
        portal: "data.gov.sg",
      },
    ],
    connector_metrics: [
      {
        metric_name: "Deal count 2024",
        metric_description: "Computed from synced rows.",
        dataset_name: "Startup dataset",
        portal: "data.gov.sg",
      },
    ],
    connector_candidates: [
      {
        title: "Candidate source",
        source_url: "https://example.test/candidate",
        data_status_label: "Metadata only",
      },
    ],
    tavily_candidates: {
      results: [{ title: "External source", source_url: "https://example.test/external" }],
    },
    comparison: {
      definition_differences: [
        { raw_variable_name: "Deals", definition: "Company-level financing events" },
      ],
    },
  },
  limitations: ["Excluded stale private spreadsheet."],
  debug: { exports: ["research_task.xlsx"] },
  tool_trace: [
    {
      id: "event-1",
      timestamp: "2026-06-01T00:00:00Z",
      type: "tool_complete",
      status: "completed",
      label: "Connector searched",
      detail: "data.gov.sg",
    },
  ],
};

describe("EvidenceWorkspacePanel", () => {
  afterEach(() => cleanup());

  it("shows the empty state when no assistant message is selected", () => {
    render(
      <EvidenceWorkspacePanel
        evidenceItem={null}
        onViewEvidence={vi.fn()}
        onClearEvidence={vi.fn()}
        onSaved={vi.fn()}
      />,
    );

    expect(screen.getByText("Evidence & Data")).toBeTruthy();
    expect(screen.getByText("Select an answer to inspect evidence, data, sources, and actions.")).toBeTruthy();
  });

  it("renders selected assistant evidence, data tables, exports, and grouped sources in the right panel", () => {
    render(
      <EvidenceWorkspacePanel
        turn={{ query: "Singapore VC deals", response: baseResponse }}
        evidenceItem={null}
        onViewEvidence={vi.fn()}
        onClearEvidence={vi.fn()}
        onSaved={vi.fn()}
      />,
    );

    expect(screen.getByText("Coverage")).toBeTruthy();
    expect(screen.getByText("strong")).toBeTruthy();
    expect(screen.getAllByText("Deal count 2024").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Startup dataset").length).toBeGreaterThan(0);
    expect(screen.getAllByText("120 x 8").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Retrieved/).length).toBeGreaterThan(0);
    expect(screen.getByText("definition_differences")).toBeTruthy();
    expect(screen.getAllByText("Company-level financing events").length).toBeGreaterThan(0);
    expect(screen.getByText("research_task.xlsx")).toBeTruthy();
    expect(screen.getByText("Source candidate, not yet synced")).toBeTruthy();
    expect(screen.getAllByText("Open source").length).toBeGreaterThan(0);
    expect(screen.queryByText("Source URL: https://data.gov.sg/startups")).toBeNull();
    expect(screen.queryByText("https://example.test/candidate")).toBeNull();
    expect(screen.getByText("Export Excel")).toBeTruthy();
    expect(screen.getByText("Export CSV")).toBeTruthy();
  });

  it("keeps excluded evidence collapsed by default", () => {
    render(
      <EvidenceWorkspacePanel
        turn={{ query: "Singapore VC deals", response: baseResponse }}
        evidenceItem={null}
        onViewEvidence={vi.fn()}
        onClearEvidence={vi.fn()}
        onSaved={vi.fn()}
      />,
    );

    const summary = screen.getByText("Excluded evidence");
    const details = summary.closest("details");
    expect(details?.hasAttribute("open")).toBe(false);
    expect(within(details as HTMLElement).getByText("1")).toBeTruthy();
  });

  it("shows metadata-only connector datasets instead of the no-match state", () => {
    const metadataOnlyResponse: ChatResponse = {
      ...baseResponse,
      type: "no_results",
      results: {
        closest_variables: [],
        relevant_reports: [],
        relevant_organizations: [],
        source_links: [],
        connector_datasets: [
          {
            title: "AI patent source candidate",
            source_url: "https://example.test/ai-patents",
            data_status_label: "Metadata only",
            portal: "OpenAlex",
          },
        ],
        connector_metrics: [],
        connector_candidates: [],
        tavily_candidates: null,
        comparison: {},
      },
      limitations: [],
    };

    render(
      <EvidenceWorkspacePanel
        turn={{ query: "Recent university research on AI patents", response: metadataOnlyResponse }}
        evidenceItem={null}
        onViewEvidence={vi.fn()}
        onClearEvidence={vi.fn()}
        onSaved={vi.fn()}
      />,
    );

    expect(screen.queryByText("No exact match for this message")).toBeNull();
    expect(screen.getByText("Coverage")).toBeTruthy();
    expect(screen.getAllByText("AI patent source candidate").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Source candidate, not yet synced").length).toBeGreaterThan(0);
    expect(screen.getByText("Metadata-only candidates")).toBeTruthy();
  });

  it("shows attached source candidates for clarification responses", () => {
    const clarificationWithSources: ChatResponse = {
      ...baseResponse,
      type: "clarification",
      message: "What aspect of university AI patent research are you interested in?",
      assistant_message: "What aspect of university AI patent research are you interested in?",
      results: {
        closest_variables: [],
        relevant_reports: [],
        relevant_organizations: [],
        source_links: [],
        connector_datasets: [],
        connector_metrics: [],
        connector_candidates: [
          {
            title: "University patent filings candidate",
            source_url: "https://example.test/university-patents",
            data_status_label: "Metadata only",
          },
        ],
        tavily_candidates: null,
        comparison: {},
      },
      limitations: [],
    };

    render(
      <EvidenceWorkspacePanel
        turn={{ query: "Recent university research on AI patents", response: clarificationWithSources }}
        evidenceItem={null}
        onViewEvidence={vi.fn()}
        onClearEvidence={vi.fn()}
        onSaved={vi.fn()}
      />,
    );

    expect(screen.getByText("Coverage")).toBeTruthy();
    expect(screen.getAllByText("University patent filings candidate").length).toBeGreaterThan(0);
    expect(screen.queryByText("Answer in the thread to load structured matches here.")).toBeNull();
  });
});
