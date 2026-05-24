import { FormEvent, useMemo, useState } from "react";
import { Send } from "lucide-react";
import { sendChat, submitFeedback, type ChatHistoryItem } from "./api";
import { ResultSections } from "./components/ResultSections";
import type { ChatResponse, ClarifyingQuestion } from "./types";

const EXAMPLES = [
  "Startup funding in Singapore",
  "VC deal count by stage",
  "R&D expenditure as % of GDP",
  "SME digital adoption",
  "Compare startup funding definitions",
  "Shenzhen startup organizations"
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
  const answerId = useMemo(() => `answer-${Date.now()}`, [turns.length]);

  function historyFromTurns(nextTurns = turns): ChatHistoryItem[] {
    return nextTurns
      .filter((turn) => turn.content.trim())
      .slice(-10)
      .map((turn) => ({ role: turn.role, content: turn.content }));
  }

  async function runQuery(query: string) {
    const trimmed = query.trim();
    if (!trimmed || loading) return;
    const userTurn: Turn = { id: crypto.randomUUID(), role: "user", content: trimmed };
    const nextTurns = [...turns, userTurn];
    setTurns(nextTurns);
    setMessage("");
    setLoading(true);
    setError("");
    try {
      const response = await sendChat(trimmed, {}, historyFromTurns(nextTurns));
      const assistantTurn: Turn = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: response.assistant_message || response.message,
        response
      };
      setTurns([...nextTurns, assistantTurn]);
    } catch (err) {
      const messageText = err instanceof Error ? err.message : "Request failed";
      setError(messageText);
      setTurns([
        ...nextTurns,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: "The demo API request failed before the agent could respond.",
          response: {
            type: "error",
            message: messageText,
            assistant_message: messageText,
            intent: "unknown",
            clarifying_questions: [],
            tool_calls: [],
            results: {
              closest_variables: [],
              relevant_reports: [],
              relevant_organizations: [],
              source_links: [],
              comparison: {}
            },
            limitations: [messageText]
          }
        }
      ]);
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void runQuery(message);
  }

  async function feedback(type: string) {
    try {
      await submitFeedback(answerId, type);
    } catch {
      setError("Feedback could not be saved.");
    }
  }

  const hasTurns = turns.length > 0;

  return (
    <main className="app-shell chat-shell">
      <header className="topbar">
        <div>
          <h1>Startup Data Intelligence Demo</h1>
          <p>Ask for variables, reports, organizations, definitions, and evidence.</p>
        </div>
      </header>

      <section className="chat-panel" aria-live="polite">
        {!hasTurns && (
          <div className="empty-state">
            <p>Ask a question about startup, VC, SME, innovation, or ecosystem data.</p>
            <div className="chips">
              {EXAMPLES.map((example) => (
                <button key={example} type="button" onClick={() => void runQuery(example)}>
                  {example}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="transcript">
          {turns.map((turn) => (
            <article className={`turn ${turn.role}`} key={turn.id}>
              <div className="turn-body">
                <p>{turn.content}</p>
                {turn.response?.tool_calls && turn.response.tool_calls.length > 0 && (
                  <ToolCallSummary calls={turn.response.tool_calls} />
                )}
                {turn.response?.clarifying_questions && turn.response.clarifying_questions.length > 0 && (
                  <QuickReplies questions={turn.response.clarifying_questions} onChoose={runQuery} />
                )}
                {turn.response && turn.response.type !== "clarification" && (
                  <>
                    <ResultSections results={turn.response.results} limitations={turn.response.limitations} />
                    <div className="feedback">
                      <button type="button" onClick={() => void feedback("thumbs_up")}>Useful</button>
                      <button type="button" onClick={() => void feedback("thumbs_down")}>Not useful</button>
                    </div>
                  </>
                )}
              </div>
            </article>
          ))}
          {loading && (
            <article className="turn assistant">
              <div className="turn-body">
                <p>Checking the data tools...</p>
              </div>
            </article>
          )}
        </div>
      </section>

      {error && <div className="notice error">{error}</div>}

      <form onSubmit={onSubmit} className="composer">
        <label htmlFor="query">Message</label>
        <div className="composer-row">
          <input
            id="query"
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder="Ask about a metric, geography, source, organization, or definition..."
          />
          <button type="submit" disabled={loading || !message.trim()} aria-label="Send message">
            <Send size={18} aria-hidden="true" />
          </button>
        </div>
      </form>
    </main>
  );
}

function QuickReplies({ questions, onChoose }: { questions: ClarifyingQuestion[]; onChoose: (value: string) => void }) {
  return (
    <div className="quick-replies">
      {questions.map((item) => (
        <div className="quick-question" key={item.question}>
          <p>{item.question}</p>
          {item.options && item.options.length > 0 && (
            <div className="option-row">
              {item.options.map((option) => (
                <button key={option} type="button" onClick={() => onChoose(option)}>
                  {option}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function ToolCallSummary({ calls }: { calls: { name: string; status: string }[] }) {
  return (
    <div className="tool-strip">
      {calls.map((call, index) => (
        <span key={`${call.name}-${index}`}>{call.name} · {call.status}</span>
      ))}
    </div>
  );
}
