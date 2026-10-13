const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type RetrievalMode = "dense" | "sparse" | "hybrid";

export interface SearchJobInfo {
  label: string;
  kind: string;
  dense: boolean;
  sparse: boolean;
  text: string;
}

export interface TransformationInfo {
  original: string;
  requested: string[];
  rewrite: string | null;
  keywords: string[];
  variants: string[];
  hyde: string | null;
  fallback_used: boolean;
  error: string | null;
  elapsed_ms: number;
  jobs: SearchJobInfo[];
}

export interface RetrievalResult {
  chunk_id: number;
  content: string;
  document_id: number;
  filename: string;
  page_number: number | null;
  dense_distance: number | null;
  sparse_score: number | null;
  rrf_score: number | null;
  rerank_score: number | null;
  pre_rerank_rank: number | null;
  post_rerank_rank: number | null;
  found_by: string[];
  found_by_queries: string[];
  above_threshold: boolean;
}

export interface RetrieveDebugResponse {
  results: RetrievalResult[];
  threshold_used: number;
  k_used: number;
  mode: RetrievalMode;
  reranked: boolean;
  transformation: TransformationInfo | null;
}

export async function retrieveDebug(
  question: string,
  k: number,
  similarityThreshold: number,
  mode: RetrievalMode,
  documentIds?: number[],
  rerank: boolean = false,
  transforms: string[] = []
): Promise<RetrieveDebugResponse> {
  const response = await fetch(`${API_BASE_URL}/query/retrieve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      k,
      similarity_threshold: similarityThreshold,
      mode,
      rerank,
      transforms,
      document_ids: documentIds && documentIds.length > 0 ? documentIds : undefined,
    }),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(
      errorBody.detail || `Retrieval debug failed with status ${response.status}`
    );
  }

  return response.json();
}