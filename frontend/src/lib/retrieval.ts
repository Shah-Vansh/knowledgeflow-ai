const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface RetrievalResult {
  chunk_id: number;
  content: string;
  distance: number;
  above_threshold: boolean;
  document_id: number;
  filename: string;
  page_number: number | null;
}

export interface RetrieveDebugResponse {
  results: RetrievalResult[];
  threshold_used: number;
  k_used: number;
}

export async function retrieveDebug(
  question: string,
  k: number,
  similarityThreshold: number,
  documentIds?: number[]
): Promise<RetrieveDebugResponse> {
  const response = await fetch(`${API_BASE_URL}/query/retrieve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      k,
      similarity_threshold: similarityThreshold,
      document_ids: documentIds && documentIds.length > 0 ? documentIds : undefined,
    }),
  });

  if (!response.ok) {
    throw new Error(`Retrieval debug failed with status ${response.status}`);
  }

  return response.json();
}