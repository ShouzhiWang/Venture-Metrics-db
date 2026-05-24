import type { ChatResponse } from "./types";

export async function sendChat(message: string, context: Record<string, unknown> = {}): Promise<ChatResponse> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, context })
  });
  if (!response.ok) {
    throw new Error(`API error ${response.status}`);
  }
  return response.json();
}

export async function submitFeedback(answerId: string, feedbackType: string, comment = "") {
  const response = await fetch("/api/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer_id: answerId, feedback_type: feedbackType, comment })
  });
  if (!response.ok) {
    throw new Error(`Feedback error ${response.status}`);
  }
  return response.json();
}
