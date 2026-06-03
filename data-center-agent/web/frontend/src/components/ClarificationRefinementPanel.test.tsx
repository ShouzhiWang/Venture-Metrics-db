/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { buildRefinedQuery, ClarificationRefinementPanel } from "./ClarificationRefinementPanel";
import type { ClarificationUi } from "../types";

const researchUi: ClarificationUi = {
  main_question: "Which angle do you want to focus on?",
  choice_options: [
    { label: "University AI patent filings", value: "University AI patent filings" },
    { label: "Research papers about AI patents", value: "Research papers about AI patents" },
  ],
  optional_fields: [
    { name: "geography", label: "Country/region", type: "text", placeholder: "e.g. Hong Kong, Singapore, China" },
    { name: "university", label: "University", type: "text", placeholder: "e.g. HKUST, NUS, Tsinghua" },
    { name: "time_period", label: "Time period", type: "text_or_chips", options: ["Last 3 years", "Last 5 years", "Since 2020"] },
    { name: "output_format", label: "Output", type: "single_select", options: ["Answer", "Table", "Excel", "Source list"] },
  ],
  suggested_searches: [
    { label: "Broader overview", query_append: "broader overview, key metrics and trends" },
    { label: "Official statistics and publications", query_append: "official statistics and publications" },
  ],
  defaults: {
    label: "Run with defaults",
    choice: "Broad overview",
    fields: { geography: "global / all available", time_period: "Last 5 years", output_format: "Answer" },
  },
};

describe("ClarificationRefinementPanel", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders geography, university, time period, and output fields", () => {
    render(<ClarificationRefinementPanel variant="clarify" ui={researchUi} questions={[]} baseQuery="Recent university research on AI patents" onRun={vi.fn()} />);

    expect(screen.getByPlaceholderText("e.g. Hong Kong, Singapore, China")).toBeTruthy();
    expect(screen.getByPlaceholderText("e.g. HKUST, NUS, Tsinghua")).toBeTruthy();
    expect(screen.getByText("Since 2020")).toBeTruthy();
    expect(screen.getByLabelText("Output")).toBeTruthy();
  });

  it("constructs a clean refined query from selected chips and inputs", () => {
    const onRun = vi.fn();
    render(<ClarificationRefinementPanel variant="clarify" ui={researchUi} questions={[]} baseQuery="Recent university research on AI patents" onRun={onRun} />);

    fireEvent.change(screen.getByPlaceholderText("e.g. Hong Kong, Singapore, China"), { target: { value: "Hong Kong" } });
    fireEvent.click(screen.getByText("Since 2020"));
    fireEvent.change(screen.getByLabelText("Output"), { target: { value: "Table" } });
    fireEvent.click(screen.getByText("Run refined search"));

    expect(onRun).toHaveBeenCalledWith("University AI patent filings in Hong Kong since 2020, output as table");
  });

  it("shows short suggested search labels instead of generated rewrites", () => {
    render(<ClarificationRefinementPanel variant="clarify" ui={researchUi} questions={[]} baseQuery="Recent university research on AI patents" onRun={vi.fn()} />);

    expect(screen.getByText("Broader overview")).toBeTruthy();
    expect(screen.queryByText(/Recent university research on AI patents.*Broader overview/)).toBeNull();
  });

  it("runs with defaults", () => {
    const onRun = vi.fn();
    render(<ClarificationRefinementPanel variant="clarify" ui={researchUi} questions={[]} baseQuery="Recent university research on AI patents" onRun={onRun} />);

    fireEvent.click(screen.getByText("Run with defaults"));

    expect(onRun).toHaveBeenCalledWith("Broad overview in global / all available last 5 years, output as answer, using default assumptions");
  });
});

describe("buildRefinedQuery", () => {
  it("does not include the original vague query when a precise choice is selected", () => {
    expect(buildRefinedQuery({
      baseQuery: "Recent university research on AI patents",
      choice: "University AI patent filings",
      fields: { geography: "Hong Kong", time_period: "Since 2020", output_format: "Table" },
    })).toBe("University AI patent filings in Hong Kong since 2020, output as table");
  });
});
