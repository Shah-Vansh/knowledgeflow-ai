const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface ConversationSource {
  document_id: number;
  filename: string;
  page_number: number | null;
  chunk_ids: number[];
  score: number;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources: ConversationSource[];
  standalone_question: string | null;
  created_at: string | null;
}

export interface ConversationSummary {
  id: number;
  workspace_id: number;
  title: string;
  created_at: string | null;
  updated_at: string | null;
  message_count?: number;
}

export interface ConversationDetail extends ConversationSummary {
  messages: ChatMessage[];
}

export interface SendMessageResponse {
  user_message: ChatMessage;
  assistant_message: ChatMessage;
  standalone_question: string;
  contextualized: boolean;
  contextualize_fallback: boolean;
  transforms_used: string[];
  transformation_fallback: boolean;
  conversation_title: string;
}

async function errorMessage(response: Response, fallback: string): Promise<string> {
  const body = await response.json().catch(() => ({}));
  return typeof body.detail === "string" ? body.detail : `${fallback} (status ${response.status})`;
}

export async function listConversations(workspaceId?: number): Promise<ConversationSummary[]> {
  const url =
    workspaceId !== undefined
      ? `${API_BASE_URL}/conversations?workspace_id=${workspaceId}`
      : `${API_BASE_URL}/conversations`;
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(await errorMessage(response, "Failed to list conversations"));
  return response.json();
}

export async function createConversation(
  workspaceId: number,
  title?: string
): Promise<ConversationSummary> {
  const response = await fetch(`${API_BASE_URL}/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workspace_id: workspaceId, title }),
  });
  if (!response.ok) throw new Error(await errorMessage(response, "Failed to create conversation"));
  return response.json();
}

export async function getConversation(id: number): Promise<ConversationDetail> {
  const response = await fetch(`${API_BASE_URL}/conversations/${id}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await errorMessage(response, "Failed to load conversation"));
  return response.json();
}

export async function deleteConversation(id: number): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/conversations/${id}`, { method: "DELETE" });
  if (!response.ok) throw new Error(await errorMessage(response, "Failed to delete conversation"));
}

// transforms: omit to use the server default (QUERY_TRANSFORMS)
export async function sendMessage(
  conversationId: number,
  content: string,
  transforms?: string[]
): Promise<SendMessageResponse> {
  const response = await fetch(`${API_BASE_URL}/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, transforms }),
  });
  if (!response.ok) throw new Error(await errorMessage(response, "Failed to send message"));
  return response.json();
}