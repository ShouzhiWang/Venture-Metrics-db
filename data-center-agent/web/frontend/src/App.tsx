import { FormEvent, useMemo, useState } from "react";
import { Search } from "lucide-react";
import { sendChat, submitFeedback } from "./api";
import { ClarifyingQuestions } from "./components/ClarifyingQuestions";
import { ResultSections } from "./components/ResultSections";
import type { ChatResponse } from "./types";

const EXAMPLES = [
  "Startup funding in Singapore",
  "VC deal count by stage",
  "R&D expenditure as % of GDP",
  "SME digital adoption",
  "Compare startup funding definitions",
  "Shenzhen startup organizations"
];

export function App() {
  const [message, setMessage] = useState("");
  const [lastQuery, setLastQuery] = useState("");
  const [response, setResponse] = useState<ChatResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const answerId = useMemo(() => `answer-${Date.now()}`, [response]);

  async function runQuery(query: string, context: Record<string, unknown> = {}) {
    if (!query.trim()) return;
    setLoading(true);
    setError("");
    setLastQuery(query);
    try {
      setResponse(await sendChat(query, context));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void runQuery(message);
  }

  function chooseClarification(option: string) {
    const combined = `${lastQuery} ${option}`;
    setMessage(combined);
    void runQuery(combined, { previous_clarification: option });
  }

  async function feedback(type: string) {
    try {
      await submitFeedback(answerId, type);
    } catch {
      setError("Feedback could not be saved.");
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>Startup Data Intelligence Demo</h1>
          <p>Find variables, reports, organizations, and data sources with evidence.</p>
        </div>
      </header>

      <section className="query-panel">
        <form onSubmit={onSubmit} className="query-form">
          <label htmlFor="query">Ask a data question</label>
          <div className="input-row">
            <Search size={18} aria-hidden="true" />
            <input
              id="query"
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder="I want startup funding data in Singapore"
            />
            <button type="submit" disabled={loading}>{loading ? "Searching" : "Ask"}</button>
          </div>
        </form>
        <div className="chips">
          {EXAMPLES.map((example) => (
            <button key={example} type="button" onClick={() => { setMessage(example); void runQuery(example); }}>
              {example}
            </button>
          ))}
        </div>
      </section>

      {error && <div className="notice error">{error}</div>}

      {response && (
        <section className="response-panel">
          <div className="summary-row">
            <div>
              <h2>{response.type === "clarification" ? "Clarification needed" : "Result"}</h2>
              <p>{response.message}</p>
            </div>
            {response.type !== "clarification" && (
              <div className="feedback">
                <button type="button" onClick={() => void feedback("thumbs_up")}>Useful</button>
                <button type="button" onClick={() => void feedback("thumbs_down")}>Not useful</button>
              </div>
            )}
          </div>

          {response.clarifying_questions.length > 0 && (
            <ClarifyingQuestions questions={response.clarifying_questions} onChoose={chooseClarification} />
          )}

          <ResultSections results={response.results} limitations={response.limitations} />
        </section>
      )}
    </main>
  );
}
