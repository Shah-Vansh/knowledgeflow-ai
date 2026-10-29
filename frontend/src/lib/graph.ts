import { AgentSource, GraphInfo } from "@/lib/agent";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface GraphNode {
  id: number;
  name: string;
  type: string;
  degree: number;
}

export interface GraphEdge {
  id: number;
  source: number;
  target: number;
  relation: string;
  filename: string | null;
  page_number: number | null;
}

export interface GraphView {
  workspace_id: number;
  totals: { entities: number; relationships: number; documents_with_graph: number };
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface BuildReport {
  document_id: number;
  chunks_total: number;
  chunks_processed: number;
  groups_total: number;
  groups_failed: number;
  llm_calls: number;
  entities: number;
  mentions: number;
  relationships: number;
  dropped_entities: number;
  dropped_relations: number;
  truncated: boolean;
  elapsed_ms: number;
}

export interface GraphAnswer {
  answer: string;
  sources: AgentSource[];
  graph: GraphInfo;
  mode: string;
}

async function errorMessage(response: Response, fallback: string): Promise<string> {
  const body = await response.json().catch(() => ({}));
  return typeof body.detail === "string" ? body.detail : `${fallback} (status ${response.status})`;
}

export async function getGraph(workspaceId: number, limit = 40): Promise<GraphView> {
  const response = await fetch(`${API_BASE_URL}/graph?workspace_id=${workspaceId}&limit=${limit}`, {
    cache: "no-store",
  });
  if (!response.ok) throw new Error(await errorMessage(response, "Failed to load the graph"));
  return response.json();
}

export async function buildGraph(
  documentId: number,
  maxChunks: number,
  groupSize: number
): Promise<BuildReport> {
  const response = await fetch(`${API_BASE_URL}/graph/documents/${documentId}/build`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ max_chunks: maxChunks, group_size: groupSize }),
  });
  if (!response.ok) throw new Error(await errorMessage(response, "Failed to build the graph"));
  return response.json();
}

export async function askGraph(
  question: string,
  workspaceId: number,
  hops: number
): Promise<GraphAnswer> {
  const response = await fetch(`${API_BASE_URL}/graph/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, workspace_id: workspaceId, hops }),
  });
  if (!response.ok) throw new Error(await errorMessage(response, "Graph query failed"));
  return response.json();
}