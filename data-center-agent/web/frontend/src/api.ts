import type { ChatResponse, MapItem, ProjectItem, ResearchProject } from "./types";

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

export type HistoryItem = {
  id: string;
  session_id?: string | null;
  title: string;
  query?: string;
  result_summary?: string;
  result_payload?: ChatResponse;
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
  history: ChatHistoryItem[] = [],
  conversationId?: string
): Promise<ChatResponse> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, context, history, conversation_id: conversationId }),
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

export async function listHistory(): Promise<HistoryItem[]> {
  const response = await fetch("/api/history", { credentials: "same-origin" });
  if (!response.ok) {
    throw new Error(response.status === 401 ? "Login is required." : `History error ${response.status}`);
  }
  const result = await response.json() as { ok: boolean; items?: HistoryItem[]; error?: { message: string } };
  if (!result.ok) {
    throw new Error(result.error?.message || "Could not load history.");
  }
  return result.items || [];
}

export async function getHistoryItem(id: string): Promise<HistoryItem> {
  const response = await fetch(`/api/history/${encodeURIComponent(id)}`, { credentials: "same-origin" });
  if (!response.ok) {
    throw new Error(response.status === 401 ? "Login is required." : `History error ${response.status}`);
  }
  const result = await response.json() as { ok: boolean; item?: HistoryItem; error?: { message: string } };
  if (!result.ok || !result.item) {
    throw new Error(result.error?.message || "Could not load history item.");
  }
  return result.item;
}

export async function listProjects(): Promise<ResearchProject[]> {
  const response = await fetch("/api/projects", { credentials: "same-origin" });
  const result = await parseJson<{ ok: boolean; projects?: ResearchProject[]; error?: { message: string } }>(response);
  if (!response.ok || !result.ok) {
    throw new Error(result.error?.message || `Projects error ${response.status}`);
  }
  return result.projects || [];
}

export async function createProject(input: {
  title: string;
  description?: string;
  research_question?: string;
}): Promise<ResearchProject> {
  const response = await fetch("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
    credentials: "same-origin"
  });
  const result = await parseJson<{ ok: boolean; project?: ResearchProject; error?: { message: string } }>(response);
  if (!response.ok || !result.ok || !result.project) {
    throw new Error(result.error?.message || `Projects error ${response.status}`);
  }
  return result.project;
}

export async function getProject(id: string): Promise<{ project: ResearchProject; items: ProjectItem[] }> {
  const response = await fetch(`/api/projects/${encodeURIComponent(id)}`, { credentials: "same-origin" });
  const result = await parseJson<{ ok: boolean; project?: ResearchProject; items?: ProjectItem[]; error?: { message: string } }>(response);
  if (!response.ok || !result.ok || !result.project) {
    throw new Error(result.error?.message || `Projects error ${response.status}`);
  }
  return { project: result.project, items: result.items || [] };
}

export async function updateProject(id: string, input: {
  title: string;
  description?: string;
  research_question?: string;
}): Promise<ResearchProject> {
  const response = await fetch(`/api/projects/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
    credentials: "same-origin"
  });
  const result = await parseJson<{ ok: boolean; project?: ResearchProject; error?: { message: string } }>(response);
  if (!response.ok || !result.ok || !result.project) {
    throw new Error(result.error?.message || `Projects error ${response.status}`);
  }
  return result.project;
}

export async function addProjectItem(projectId: string, input: {
  item_type: ProjectItem["item_type"];
  item_id?: string | null;
  title?: string | null;
  note?: string | null;
  metadata?: Record<string, unknown>;
}): Promise<ProjectItem> {
  const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/items`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
    credentials: "same-origin"
  });
  const result = await parseJson<{ ok: boolean; item?: ProjectItem; error?: { message: string } }>(response);
  if (!response.ok || !result.ok || !result.item) {
    throw new Error(result.error?.message || `Projects error ${response.status}`);
  }
  return result.item;
}

export async function updateProjectItemNote(itemId: string, note: string): Promise<ProjectItem> {
  const response = await fetch(`/api/projects/items/${encodeURIComponent(itemId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
    credentials: "same-origin"
  });
  const result = await parseJson<{ ok: boolean; item?: ProjectItem; error?: { message: string } }>(response);
  if (!response.ok || !result.ok || !result.item) {
    throw new Error(result.error?.message || `Projects error ${response.status}`);
  }
  return result.item;
}

export async function removeProjectItem(itemId: string): Promise<void> {
  const response = await fetch(`/api/projects/items/${encodeURIComponent(itemId)}`, {
    method: "DELETE",
    credentials: "same-origin"
  });
  const result = await parseJson<{ ok: boolean; error?: { message: string } }>(response);
  if (!response.ok || !result.ok) {
    throw new Error(result.error?.message || `Projects error ${response.status}`);
  }
}

export async function exportProjectMarkdown(id: string): Promise<string> {
  const response = await fetch(`/api/projects/${encodeURIComponent(id)}/export.md`, { credentials: "same-origin" });
  const result = await parseJson<{ ok: boolean; markdown?: string; error?: { message: string } }>(response);
  if (!response.ok || !result.ok) {
    throw new Error(result.error?.message || `Projects error ${response.status}`);
  }
  return result.markdown || "";
}

export async function listMapItems(): Promise<MapItem[]> {
  const response = await fetch("/api/map/items", { credentials: "same-origin" });
  if (!response.ok) {
    throw new Error(`Map error ${response.status}`);
  }
  return response.json();
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

async function parseJson<T>(response: Response): Promise<T> {
  try {
    return await response.json() as T;
  } catch {
    return { ok: false, error: { message: `Request failed with status ${response.status}` } } as T;
  }
}

function requireUser(result: AuthResponse): User {
  if (!result.user) {
    throw new Error("Authentication response did not include a user.");
  }
  return result.user;
}
