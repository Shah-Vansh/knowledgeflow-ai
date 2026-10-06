const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Source {
  document_id: number;
  filename: string;
  page_number: number | null;
  chunk_ids: number[];
  distance: number;
}

export interface QueryResponse {
  answer: string;
  sources: Source[];
}

export async function askQuestion(question: string, documentIds?: number[]): Promise<QueryResponse> {
  const response = await fetch(`${API_BASE_URL}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      document_ids: documentIds && documentIds.length > 0 ? documentIds : undefined,
    }),
  });

  if (!response.ok) {
    throw new Error(`Query failed with status ${response.status}`);
  }

  return response.json();
}