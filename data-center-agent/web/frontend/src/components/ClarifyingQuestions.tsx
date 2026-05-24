import { FormEvent, useState } from "react";
import type { ClarifyingQuestion } from "../types";

type Props = {
  questions: ClarifyingQuestion[];
  onChoose: (option: string) => void;
  onReply: (reply: string) => void;
  loading?: boolean;
};

export function ClarifyingQuestions({ questions, onChoose, onReply, loading = false }: Props) {
  const [reply, setReply] = useState("");

  function submitReply(event: FormEvent) {
    event.preventDefault();
    const trimmed = reply.trim();
    if (!trimmed) return;
    onReply(trimmed);
    setReply("");
  }

  return (
    <section className="section-block">
      <h3>Clarifying questions</h3>
      <div className="question-list">
        {questions.map((item) => (
          <div className="question-card" key={item.question}>
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
            {(!item.options || item.options.length === 0) && (
              <p className="question-hint">Answer below, or use the main input at the top.</p>
            )}
          </div>
        ))}
      </div>
      <form className="clarification-reply" onSubmit={submitReply}>
        <label htmlFor="clarification-reply-input">Your reply</label>
        <div className="reply-row">
          <input
            id="clarification-reply-input"
            value={reply}
            onChange={(event) => setReply(event.target.value)}
            placeholder="e.g. 2020-2024, stage breakdown, public sources only"
          />
          <button type="submit" disabled={loading || !reply.trim()}>
            {loading ? "Searching" : "Continue"}
          </button>
        </div>
      </form>
    </section>
  );
}
