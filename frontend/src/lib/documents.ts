const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface UploadResponse {
  document_id: number;
  filename: string;
  status: string;
}

export interface DocumentSummary {
  id: number;
  filename: string;
  status: string;
}

export interface ChunkInfo {
  id: number;
  chunk_index: number;
  content: string;
  strategy: string | null;
  chunk_size: number | null;
  overlap: number | null;
}

export interface RechunkResponse {
  document_id: number;
  chunk_count: number;
}

export interface ChunkConfig {
  strategy: string;
  chunk_size: number;
  overlap: number;
}

export async function uploadDocument(file: File, config?: ChunkConfig): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (config) {
    formData.append("strategy", config.strategy);
    formData.append("chunk_size", String(config.chunk_size));
    formData.append("overlap", String(config.overlap));
  }

  const response = await fetch(`${API_BASE_URL}/documents/upload`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `Upload failed with status ${response.status}`);
  }

  return response.json();
}

export async function listDocuments(): Promise<DocumentSummary[]> {
  const response = await fetch(`${API_BASE_URL}/documents`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to list documents (status ${response.status})`);
  }
  return response.json();
}

export async function getDocumentChunks(documentId: number): Promise<ChunkInfo[]> {
  const response = await fetch(`${API_BASE_URL}/documents/${documentId}/chunks`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to fetch chunks (status ${response.status})`);
  }
  return response.json();
}

export async function rechunkDocument(documentId: number, config: ChunkConfig): Promise<RechunkResponse> {
  const response = await fetch(`${API_BASE_URL}/documents/${documentId}/rechunk`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `Rechunk failed with status ${response.status}`);
  }

  return response.json();
}