import type { ChatResponse } from "./types";

export type ChatHistoryItem = {
  role: "user" | "assistant";
  content: string;
};

export async function sendChat(
  message: string,
  context: Record<string, unknown> = {},
  history: ChatHistoryItem[] = []
): Promise<ChatResponse> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, context, history })
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
