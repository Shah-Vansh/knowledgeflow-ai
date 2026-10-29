const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface AgentSource {
  document_id: number;
  filename: string;
  page_number: number | null;
  chunk_ids: number[];
  score: number;
}

export interface GraphFact {
  source: string;
  relation: string;
  target: string;
  chunk_id: number;
  document_id: number;
  filename: string;
  page_number: number | null;
  hop: number;
}

export interface GraphInfo {
  matched_entities: string[];
  facts: GraphFact[];
  hops: number;
  used: boolean;
}

export interface TraceStep {
  step: string;
  detail: string;
  ms: number;
}

export interface AgentResponse {
  answer: string;
  route: string;
  used_route: string;
  route_fallback: boolean;
  fallback_to_rag: boolean;
  fallback_reason: string | null;
  sources: AgentSource[];
  tool_result: Record<string, unknown> | null;
  graph: GraphInfo | null;
  trace: TraceStep[];
  llm_calls: number;
}

export async function askAgent(question: string, workspaceId: number): Promise<AgentResponse> {
  const response = await fetch(`${API_BASE_URL}/agent/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, workspace_id: workspaceId }),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string" ? body.detail : `Agent request failed (status ${response.status})`
    );
  }

  return response.json();
}