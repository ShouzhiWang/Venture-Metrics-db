import type { ChatResponse } from "./types";

export type ChatHistoryItem = {
  role: "user" | "assistant";
  content: string;
};

export type User = {
  id: string;
  name?: string | null;
  email: string;
  created_at?: string;
};

type AuthResponse = {
  ok: boolean;
  user?: User | null;
  error?: {
    code: string;
    message: string;
    status?: number;
  };
};

export async function sendChat(
  message: string,
  context: Record<string, unknown> = {},
  history: ChatHistoryItem[] = []
): Promise<ChatResponse> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, context, history }),
    credentials: "same-origin"
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
    body: JSON.stringify({ answer_id: answerId, feedback_type: feedbackType, comment }),
    credentials: "same-origin"
  });
  if (!response.ok) {
    throw new Error(`Feedback error ${response.status}`);
  }
  return response.json();
}

export async function register(name: string, email: string, password: string): Promise<User> {
  const result = await authRequest("/api/auth/register", { name, email, password });
  return requireUser(result);
}

export async function login(email: string, password: string): Promise<User> {
  const result = await authRequest("/api/auth/login", { email, password });
  return requireUser(result);
}

export async function logout(): Promise<void> {
  await fetch("/api/auth/logout", {
    method: "POST",
    credentials: "same-origin"
  });
}

export async function getCurrentUser(): Promise<User | null> {
  const response = await fetch("/api/auth/me", { credentials: "same-origin" });
  if (!response.ok) {
    throw new Error(`Auth error ${response.status}`);
  }
  const result = await response.json() as AuthResponse;
  return result.user ?? null;
}

async function authRequest(url: string, body: Record<string, string>): Promise<AuthResponse> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    credentials: "same-origin"
  });
  const result = await response.json() as AuthResponse;
  if (!response.ok && !result.error) {
    throw new Error(`Auth error ${response.status}`);
  }
  if (!result.ok) {
    throw new Error(result.error?.message || "Authentication failed.");
  }
  return result;
}

function requireUser(result: AuthResponse): User {
  if (!result.user) {
    throw new Error("Authentication response did not include a user.");
  }
  return result.user;
}
