export type ClarifyingQuestion = {
  dimension?: string;
  question: string;
  options?: string[];
};

export type FollowUpQuery = {
  label: string;
  query: string;
};

export type VariableResult = {
  id?: string;
  object_id?: string;
  variable_id?: string;
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
  id?: string;
  object_id?: string;
  report_id?: string;
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
  id?: string;
  object_id?: string;
  organization_id?: string;
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
  id?: string;
  object_id?: string;
  source_id?: string;
  title?: string;
  source_url?: string;
  availability?: string;
  local_path?: string;
};

export type AgentEvent = {
  id: string;
  timestamp: string;
  type:
    | "planning"
    | "tool_start"
    | "tool_progress"
    | "tool_complete"
    | "fallback"
    | "answer_generation"
    | "warning"
    | "error";
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  label: string;
  detail: string;
  tool_name?: string;
  metadata?: {
    intent?: string;
    object_types?: string[];
    variable_count?: number;
    report_count?: number;
    source_count?: number;
    organization_count?: number;
    comparison_count?: number;
    duration_ms?: number;
  };
};

export type ChatResponse = {
  type: "clarification" | "answer" | "no_results" | "error";
  message: string;
  assistant_message?: string;
  conversation_id?: string;
  saved_result_id?: string;
  intent: string;
  clarifying_questions: ClarifyingQuestion[];
  refinement_chips?: ClarifyingQuestion[];
  follow_up_queries?: FollowUpQuery[];
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
  tool_trace?: AgentEvent[];
  debug?: Record<string, unknown>;
};

export type ResearchProject = {
  id: string;
  title: string;
  description?: string | null;
  research_question?: string | null;
  item_count?: number;
  created_at?: string;
  updated_at?: string;
};

export type ProjectItem = {
  id: string;
  project_id: string;
  item_type: "variable" | "report" | "source" | "organization" | "concept" | "chat_session" | "search_result" | "note";
  item_id?: string | null;
  title?: string | null;
  note?: string | null;
  metadata: Record<string, unknown>;
  created_at?: string;
};

export type MapItem = {
  id: string;
  type: "organization" | "report" | "variable" | "source";
  title: string;
  description?: string | null;
  country?: string | null;
  city?: string | null;
  lat: number;
  lng: number;
  availability?: string | null;
  metadata: Record<string, unknown>;
};
