import { FormEvent, useMemo, useState } from "react";
import type { ClarificationUi, ClarifyingQuestion } from "../types";

type Props = {
  variant: "clarify" | "narrow";
  ui?: ClarificationUi;
  questions: ClarifyingQuestion[];
  baseQuery?: string;
  onRun: (query: string) => void;
};

type RefinedQueryInput = {
  baseQuery?: string;
  choice?: string;
  fields?: Record<string, string>;
  queryAppend?: string;
  defaultsUsed?: boolean;
};

export function buildRefinedQuery({
  baseQuery,
  choice,
  fields = {},
  queryAppend,
  defaultsUsed = false,
}: RefinedQueryInput): string {
  const base = clean(baseQuery);
  const parts: string[] = [];
  if (choice) parts.push(clean(choice));
  if (fields.geography) parts.push(`in ${clean(fields.geography)}`);
  if (fields.university) parts.push(`for ${clean(fields.university)}`);
  if (fields.time_period) parts.push(timePhrase(clean(fields.time_period)));
  if (queryAppend) parts.push(clean(queryAppend));

  let query = parts.filter(Boolean).join(" ").trim();
  if (!query) query = base;
  else if (!choice && base && !query.toLowerCase().includes(base.toLowerCase()) && !base.toLowerCase().includes(query.toLowerCase())) {
    query = `${query} related to ${base}`;
  }

  const suffixes = [];
  if (fields.output_format) suffixes.push(`output as ${clean(fields.output_format).toLowerCase()}`);
  if (fields.availability) suffixes.push(clean(fields.availability).toLowerCase());
  if (defaultsUsed) suffixes.push("using default assumptions");
  return suffixes.length ? `${query}, ${suffixes.join(", ")}` : query;
}

export function ClarificationRefinementPanel({ variant, ui, questions, baseQuery, onRun }: Props) {
  const fallbackUi = useMemo(() => uiFromQuestions(questions), [questions]);
  const activeUi: ClarificationUi = hasClarificationUi(ui) ? (ui as ClarificationUi) : fallbackUi;
  const [choice, setChoice] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});

  const options = activeUi.choice_options || [];
  const optionalFields = activeUi.optional_fields || [];
  const suggestions = activeUi.suggested_searches || [];
  const selectedValue = choice || options[0]?.value || "";

  function updateField(name: string, value: string) {
    setFields(prev => ({ ...prev, [name]: value }));
  }

  function run(event?: FormEvent) {
    event?.preventDefault();
    const query = buildRefinedQuery({ baseQuery, choice: selectedValue, fields });
    if (query.trim()) onRun(query);
  }

  function runSuggestion(queryAppend: string) {
    const query = buildRefinedQuery({ baseQuery, choice: selectedValue, fields, queryAppend });
    if (query.trim()) onRun(query);
  }

  function runDefaults() {
    const defaults = activeUi.defaults || {};
    const query = buildRefinedQuery({
      baseQuery,
      choice: defaults.choice || selectedValue || "Broad overview",
      fields: defaults.fields || {},
      defaultsUsed: true,
    });
    if (query.trim()) onRun(query);
  }

  return (
    <form className={`clarification-refinement-panel ${variant}`} onSubmit={run}>
      <div className="clarification-section">
        <h3>{activeUi.main_question || "What should I focus on?"}</h3>
        {options.length > 0 && (
          <div className="clarification-choice-grid">
            {options.map(option => (
              <button
                key={`${option.label}-${option.value}`}
                type="button"
                className={selectedValue === option.value ? "selected" : undefined}
                aria-pressed={selectedValue === option.value}
                onClick={() => setChoice(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {optionalFields.length > 0 && (
        <div className="clarification-section">
          <h3>Optional filters</h3>
          <div className="clarification-field-grid">
            {optionalFields.map(field => (
              <label key={field.name} className="clarification-field">
                <span>{field.label}</span>
                {field.type === "single_select" ? (
                  <select value={fields[field.name] || ""} onChange={event => updateField(field.name, event.target.value)}>
                    <option value="">Any</option>
                    {(field.options || []).map(option => <option key={option} value={option}>{option}</option>)}
                  </select>
                ) : (
                  <>
                    {field.type === "text_or_chips" && field.options && (
                      <div className="field-chip-row">
                        {field.options.map(option => (
                          <button
                            key={option}
                            type="button"
                            className={fields[field.name] === option ? "selected" : undefined}
                            onClick={() => updateField(field.name, option)}
                          >
                            {option}
                          </button>
                        ))}
                      </div>
                    )}
                    <input
                      value={fields[field.name] || ""}
                      onChange={event => updateField(field.name, event.target.value)}
                      placeholder={field.placeholder || "Optional"}
                    />
                  </>
                )}
              </label>
            ))}
          </div>
        </div>
      )}

      {suggestions.length > 0 && (
        <div className="clarification-section">
          <h3>Suggested searches</h3>
          <div className="suggested-search-row">
            {suggestions.map(suggestion => (
              <button key={suggestion.label} type="button" onClick={() => runSuggestion(suggestion.query_append)}>
                {suggestion.label}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="clarification-actions">
        <button type="submit">Run refined search</button>
        {variant === "clarify" && (
          <button type="button" className="secondary" onClick={runDefaults}>
            {activeUi.defaults?.label || "Run with defaults"}
          </button>
        )}
      </div>
    </form>
  );
}

function hasClarificationUi(ui?: ClarificationUi): boolean {
  return Boolean(ui?.main_question || ui?.choice_options?.length || ui?.optional_fields?.length || ui?.suggested_searches?.length);
}

function uiFromQuestions(questions: ClarifyingQuestion[]): ClarificationUi {
  const first = questions[0];
  return {
    main_question: first?.question || "What should I focus on?",
    choice_options: (first?.options || []).map(option => ({ label: shortLabel(option), value: option })),
    optional_fields: [],
    suggested_searches: [],
    defaults: { label: "Run with defaults", choice: first?.options?.[0] || "Broad overview", fields: {} },
  };
}

function shortLabel(value: string): string {
  const cleanValue = clean(value);
  const separator = cleanValue.includes(" - ") ? " - " : cleanValue.includes(" — ") ? " — " : "";
  const label = separator ? cleanValue.split(separator).slice(-1)[0] : cleanValue;
  return label.length > 56 ? `${label.slice(0, 53)}...` : label;
}

function clean(value?: string): string {
  return (value || "").replace(/\s+/g, " ").trim();
}

function timePhrase(value: string): string {
  const lowered = value.toLowerCase();
  if (lowered.startsWith("since ") || lowered.startsWith("last ") || lowered.startsWith("past ")) return lowered;
  if (/^(?:19|20)\d{2}$/.test(value)) return `in ${value}`;
  return value;
}
