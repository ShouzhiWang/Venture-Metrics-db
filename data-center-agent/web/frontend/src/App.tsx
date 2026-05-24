import { FormEvent, useState } from "react";
import { Search } from "lucide-react";
import { sendChat, submitFeedback, type ChatHistoryItem } from "./api";
import { AnswerSummary } from "./components/AnswerSummary";
import { ResultSections } from "./components/ResultSections";
import { DetailDrawer, type DrawerItem } from "./components/DetailDrawer";
import type { ChatResponse, ClarifyingQuestion } from "./types";

const EXAMPLES = [
  "Startup funding in Singapore",
  "VC deal count by stage",
  "R&D expenditure as % of GDP",
  "SME digital adoption",
  "Compare startup funding definitions",
  "Shenzhen startup organizations",
];

type Turn = {
  id: string;
  role: "user" | "assistant";
  content: string;
  response?: ChatResponse;
};

export function App() {
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [drawerItem, setDrawerItem] = useState<DrawerItem | null>(null);
  const [lastQuery, setLastQuery] = useState("");
  const [answerId, setAnswerId] = useState(() => `answer-${Date.now()}`);

  const latestAssistant = [...turns].reverse().find(t => t.role === "assistant");
  const hasTurns = turns.length > 0;

  function historyFromTurns(nextTurns = turns): ChatHistoryItem[] {
    return nextTurns
      .filter(t => t.content.trim())
      .slice(-10)
      .map(t => ({ role: t.role, content: t.content }));
  }

  async function runQuery(query: string) {
    const trimmed = query.trim();
    if (!trimmed || loading) return;
    setLastQuery(trimmed);
    setDrawerItem(null);
    const userTurn: Turn = { id: crypto.randomUUID(), role: "user", content: trimmed };
    const nextTurns = [...turns, userTurn];
    setTurns(nextTurns);
    setMessage("");
    setLoading(true);
    setError("");
    setAnswerId(`answer-${Date.now()}`);
    try {
      const response = await sendChat(trimmed, {}, historyFromTurns(nextTurns));
      const assistantTurn: Turn = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: response.assistant_message || response.message,
        response,
      };
      setTurns([...nextTurns, assistantTurn]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Request failed";
      setError(msg);
      setTurns([
        ...nextTurns,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: "The demo API request failed before the agent could respond.",
          response: {
            type: "error",
            message: msg,
            assistant_message: msg,
            intent: "unknown",
            clarifying_questions: [],
            tool_calls: [],
            results: {
              closest_variables: [],
              relevant_reports: [],
              relevant_organizations: [],
              source_links: [],
              comparison: {},
            },
            limitations: [msg],
          },
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void runQuery(message);
  }

  function handleChipClick(option: string) {
    const refined = lastQuery ? `${lastQuery}, ${option}` : option;
    void runQuery(refined);
  }

  async function feedback(type: string) {
    try {
      await submitFeedback(answerId, type);
    } catch {
      setError("Feedback could not be saved.");
    }
  }

  const latestResponse = latestAssistant?.response;
  const isClarification = latestResponse?.type === "clarification";
  const hasResults = latestResponse && latestResponse.type !== "clarification";
  const clarifyingQuestions = latestResponse?.clarifying_questions ?? [];

  return (
    <div className="page-shell">
      <header className="topbar">
        <span className="site-name">Startup Data Intelligence</span>
        <span className="site-tag">Demo</span>
      </header>

      <main className="main-content">
        {/* Search input */}
        <div className="search-area">
          <form onSubmit={onSubmit}>
            <div className="search-row">
              <Search size={17} className="search-icon" aria-hidden="true" />
              <input
                value={message}
                onChange={e => setMessage(e.target.value)}
                placeholder="Ask about a metric, geography, source, organization, or definition…"
                autoFocus
                aria-label="Search query"
              />
              <button type="submit" disabled={loading || !message.trim()}>
                {loading ? "Searching…" : "Search"}
              </button>
            </div>
          </form>

          {!hasTurns && (
            <div className="example-chips">
              {EXAMPLES.map(ex => (
                <button
                  key={ex}
                  type="button"
                  className="chip"
                  onClick={() => void runQuery(ex)}
                >
                  {ex}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Error */}
        {error && <div className="notice error">{error}</div>}

        {/* Answer area */}
        {(latestResponse || loading) && (
          <div className="result-area">
            {/* First-search loading state (no previous result yet) */}
            {loading && !latestResponse && <SearchingState />}

            {latestResponse && (
              <>
                {loading && <SearchingBanner />}
                <AnswerSummary response={latestResponse} loading={loading} />
              </>
            )}

            {/* Clarification panel (when type === "clarification") */}
            {isClarification && clarifyingQuestions.length > 0 && (
              <ClarificationPanel
                questions={clarifyingQuestions}
                lastQuery={lastQuery}
                onChoose={handleChipClick}
              />
            )}

            {/* Narrow chips (when results + clarifying questions) */}
            {hasResults && clarifyingQuestions.length > 0 && (
              <NarrowChips
                questions={clarifyingQuestions}
                lastQuery={lastQuery}
                onChoose={handleChipClick}
              />
            )}

            {/* Result tabs */}
            {hasResults && latestResponse && (
              <ResultSections
                results={latestResponse.results}
                limitations={latestResponse.limitations}
                onViewEvidence={setDrawerItem}
              />
            )}

            {/* Feedback */}
            {hasResults && !loading && (
              <div className="feedback-row">
                <button type="button" onClick={() => void feedback("thumbs_up")}>
                  Useful
                </button>
                <button type="button" onClick={() => void feedback("thumbs_down")}>
                  Not useful
                </button>
              </div>
            )}
          </div>
        )}
      </main>

      <DetailDrawer item={drawerItem} onClose={() => setDrawerItem(null)} />
    </div>
  );
}

const SEARCH_STEPS = [
  "Analyzing your query…",
  "Searching variable database…",
  "Matching relevant reports…",
  "Finding organizations…",
  "Compiling results…",
];

function SearchingState() {
  return (
    <div className="searching-state">
      <div className="searching-spinner" aria-hidden="true" />
      <div className="searching-steps">
        {SEARCH_STEPS.map((step, i) => (
          <span key={step} className="searching-step" style={{ animationDelay: `${i * 0.55}s` }}>
            {step}
          </span>
        ))}
      </div>
    </div>
  );
}

function SearchingBanner() {
  return (
    <div className="searching-banner" aria-live="polite">
      <div className="searching-spinner small" aria-hidden="true" />
      <span>Searching…</span>
    </div>
  );
}

function ClarificationPanel({
  questions,
  lastQuery,
  onChoose,
}: {
  questions: ClarifyingQuestion[];
  lastQuery: string;
  onChoose: (option: string) => void;
}) {
  return (
    <div className="clarification-panel">
      <p>Could you clarify what you&rsquo;re looking for?</p>
      {questions.map(q => (
        <div className="clarification-question" key={q.question}>
          <p>{q.question}</p>
          {q.options && q.options.length > 0 && (
            <div className="example-chips">
              {q.options.map(opt => (
                <button
                  key={opt}
                  type="button"
                  className="chip"
                  onClick={() => onChoose(lastQuery ? `${lastQuery}, ${opt}` : opt)}
                >
                  {opt}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function NarrowChips({
  questions,
  lastQuery,
  onChoose,
}: {
  questions: ClarifyingQuestion[];
  lastQuery: string;
  onChoose: (option: string) => void;
}) {
  const allOptions = questions.flatMap(q => q.options ?? []);
  if (allOptions.length === 0) return null;

  return (
    <div className="narrow-section">
      <span className="narrow-label">Narrow your search:</span>
      {allOptions.map(opt => (
        <button
          key={opt}
          type="button"
          className="chip"
          onClick={() => onChoose(lastQuery ? `${lastQuery}, ${opt}` : opt)}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}
