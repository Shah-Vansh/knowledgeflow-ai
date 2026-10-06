const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface ChunkUsed {
  chunk_id: number;
  document_id: number;
  chunk_index: number;
  distance: number;
}

export interface QueryResponse {
  answer: string;
  chunks_used: ChunkUsed[];
}

export async function askQuestion(question: string): Promise<QueryResponse> {
  const response = await fetch(`${API_BASE_URL}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });

  if (!response.ok) {
    throw new Error(`Query failed with status ${response.status}`);
  }

  return response.json();
}