const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Source {
  document_id: number;
  filename: string;
  page_number: number | null;
  chunk_ids: number[];
  score: number;
}

export interface QueryResponse {
  answer: string;
  sources: Source[];
  transforms_used?: string[];
  transformation_fallback?: boolean;
}

// transforms: omit to use the server default (QUERY_TRANSFORMS); pass [] for none.
export async function askQuestion(
  question: string,
  documentIds?: number[],
  transforms?: string[]
): Promise<QueryResponse> {
  const response = await fetch(`${API_BASE_URL}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      document_ids: documentIds && documentIds.length > 0 ? documentIds : undefined,
      transforms,
    }),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `Query failed with status ${response.status}`);
  }

  return response.json();
}