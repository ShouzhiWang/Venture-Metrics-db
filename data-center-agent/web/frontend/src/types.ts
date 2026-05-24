export type ClarifyingQuestion = {
  question: string;
  options?: string[];
};

export type VariableResult = {
  title?: string;
  raw_variable_name?: string;
  definition?: string;
  measurement_method?: string;
  data_source?: string;
  availability?: string;
  temporal_coverage?: string;
  geographic_coverage?: string;
  evidence_quote?: string;
  source_url?: string;
  local_path?: string;
  report_id?: string;
  source_id?: string;
  score?: number;
};

export type ReportResult = {
  title?: string;
  publisher?: string;
  report_year?: string | number;
  geography?: string;
  geographic_coverage?: string;
  source_url?: string;
  local_path?: string;
  why_it_matched?: string;
  score?: number;
  matched_variables?: VariableResult[];
};

export type OrganizationResult = {
  name?: string;
  title?: string;
  organization_type?: string;
  geography?: string;
  description?: string;
  website_url?: string;
  source_url?: string;
  score?: number;
};

export type SourceLink = {
  title?: string;
  source_url?: string;
  availability?: string;
  local_path?: string;
};

export type ChatResponse = {
  type: "clarification" | "answer" | "no_results" | "error";
  message: string;
  assistant_message?: string;
  intent: string;
  clarifying_questions: ClarifyingQuestion[];
  tool_calls?: {
    name: string;
    args: Record<string, unknown>;
    status: string;
  }[];
  results: {
    closest_variables: VariableResult[];
    relevant_reports: ReportResult[];
    relevant_organizations: OrganizationResult[];
    source_links: SourceLink[];
    comparison: Record<string, unknown>;
  };
  limitations: string[];
  debug?: Record<string, unknown>;
};
