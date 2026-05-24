import type { ReactNode } from "react";
import type { ChatResponse } from "../types";

type Props = {
  response: ChatResponse;
  loading: boolean;
};

export function AnswerSummary({ response, loading }: Props) {
  const msg = response.assistant_message || response.message;
  const varCount = response.results?.closest_variables?.length ?? 0;
  const rptCount = response.results?.relevant_reports?.length ?? 0;
  const orgCount = response.results?.relevant_organizations?.length ?? 0;
  const privateCount = [
    ...(response.results?.closest_variables ?? []),
    ...(response.results?.source_links ?? []),
  ].filter(item => {
    const av = (item.availability ?? "").toLowerCase();
    return av.includes("private") || av.includes("unclear") || av === "";
  }).length;

  const toolCalls = response.tool_calls ?? [];
  const hasLimitations = (response.limitations?.length ?? 0) > 0;

  return (
    <div className="answer-summary">
      {loading ? (
        <p className="answer-text answer-loading">Searching the data tools&hellip;</p>
      ) : (
        <p className="answer-text">
          <MarkdownText text={msg} />
        </p>
      )}

      <div className="answer-meta">
        {varCount > 0 && (
          <span>{varCount} variable{varCount !== 1 ? "s" : ""}</span>
        )}
        {rptCount > 0 && (
          <span>{rptCount} report{rptCount !== 1 ? "s" : ""}</span>
        )}
        {orgCount > 0 && (
          <span>{orgCount} org{orgCount !== 1 ? "s" : ""}</span>
        )}
        {privateCount > 0 && (
          <span>{privateCount} private/unclear</span>
        )}
        {toolCalls.map((call, i) => (
          <span key={i} className="debug-badge">{call.name} · {call.status}</span>
        ))}
      </div>

      {hasLimitations && (
        <details className="limitations-toggle">
          <summary>Limitations</summary>
          <ul>
            {response.limitations.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function MarkdownText({ text }: { text: string }) {
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
