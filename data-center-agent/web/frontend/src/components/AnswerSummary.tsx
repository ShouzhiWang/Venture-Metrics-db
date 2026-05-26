import type { ReactNode } from "react";
import type { ChatResponse } from "../types";

type Props = {
  response: ChatResponse;
  loading: boolean;
};

export function AnswerSummary({ response, loading }: Props) {
  const msg = response.assistant_message || response.message;

  return (
    <div className="answer-summary">
      {loading ? (
        <p className="answer-text answer-loading">Searching variables, reports, sources, and organizations&hellip;</p>
      ) : (
        <p className="answer-text">
          <MarkdownText text={msg} />
        </p>
      )}
    </div>
  );
}

export function MarkdownText({ text }: { text: string }) {
  const nodes: ReactNode[] = [];
  const linkRe = /\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g;
  let last = 0;
  let m: RegExpExecArray | null;

  while ((m = linkRe.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    nodes.push(
      <a key={m.index} href={m[2]} target="_blank" rel="noreferrer">
        {m[1]}
      </a>
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));

  return <>{nodes}</>;
}
