import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Check, Loader2, X } from "lucide-react";
import type { AgentEvent } from "../types";
import {
  buildTimelineSummary,
  decorateProgressiveSteps,
  loadingPlaceholderSequence,
  LOADING_STEP_MS,
} from "./agentActivityUtils";

type Props = {
  events?: AgentEvent[];
  defaultCollapsed?: boolean;
  isLoading?: boolean;
};

export function AgentActivityTimeline({ events = [], defaultCollapsed = true, isLoading = false }: Props) {
  const [expanded, setExpanded] = useState(!defaultCollapsed);
  const hasLiveEvents = events.length > 0;
  const usingPlaceholders = isLoading && !hasLiveEvents;
  const sourceEvents = hasLiveEvents ? events : usingPlaceholders ? loadingPlaceholderSequence() : [];
  const sourceKey = usingPlaceholders ? "loading" : "live";
  const visibleCount = useProgressiveReveal(
    sourceKey,
    sourceEvents.length,
    LOADING_STEP_MS,
    usingPlaceholders,
    usingPlaceholders,
  );

  const visibleEvents = useMemo(() => {
    if (hasLiveEvents) return events;
    return decorateProgressiveSteps(
      sourceEvents.slice(0, visibleCount),
      visibleCount < sourceEvents.length,
    );
  }, [hasLiveEvents, events, sourceEvents, visibleCount]);

  const inProgress = isLoading || (usingPlaceholders && visibleCount < sourceEvents.length);
  const summary = useMemo(
    () => buildTimelineSummary(hasLiveEvents ? events : visibleEvents, inProgress),
    [hasLiveEvents, events, visibleEvents, inProgress],
  );

  if (!isLoading && events.length === 0) return null;

  return (
    <section className="agent-activity-timeline" aria-live="polite">
      <button
        type="button"
        className="agent-activity-toggle"
        onClick={() => setExpanded(value => !value)}
        aria-expanded={expanded}
      >
        <span className="agent-activity-toggle-label">{summary}</span>
        <span className="agent-activity-toggle-hint">{expanded ? "Hide" : "Show"}</span>
      </button>

      {expanded && (
        <ol className="agent-activity-steps">
          {visibleEvents.map(event => (
            <li key={event.id} className={`agent-activity-step status-${event.status}`}>
              <span className="agent-activity-icon" aria-hidden="true">
                <StepIcon status={event.status} />
              </span>
              <div className="agent-activity-copy">
                <strong>{event.label}</strong>
                {event.detail && <p>{event.detail}</p>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function useProgressiveReveal(
  sourceKey: string,
  total: number,
  paceMs: number,
  active: boolean,
  enabled: boolean,
) {
  const [visibleCount, setVisibleCount] = useState(0);

  useEffect(() => {
    if (!active || total === 0) {
      setVisibleCount(0);
      return;
    }
    if (!enabled) {
      setVisibleCount(total);
      return;
    }

    setVisibleCount(1);
    if (total <= 1) return;

    let count = 1;
    const id = window.setInterval(() => {
      count += 1;
      setVisibleCount(count);
      if (count >= total) window.clearInterval(id);
    }, paceMs);

    return () => window.clearInterval(id);
  }, [sourceKey, active, total, enabled, paceMs]);

  return visibleCount;
}

function StepIcon({ status }: { status: AgentEvent["status"] }) {
  if (status === "running") return <Loader2 size={14} className="agent-icon-spin" />;
  if (status === "failed") return <X size={14} />;
  if (status === "completed") return <Check size={14} />;
  if (status === "pending") return <Loader2 size={14} className="agent-icon-spin agent-icon-muted" />;
  return <AlertTriangle size={14} />;
}
