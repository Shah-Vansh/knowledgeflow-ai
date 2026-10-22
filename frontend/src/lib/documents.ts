const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface UploadResponse {
  document_id: number;
  filename: string;
  status: string;
  workspace_id: number;
}

export interface DocumentSummary {
  id: number;
  filename: string;
  status: string;
  page_count: number | null;
  source_type: string | null;
  workspace_id: number;
  uploaded_at: string | null;
}

export interface ChunkInfo {
  id: number;
  chunk_index: number;
  content: string;
  strategy: string | null;
  chunk_size: number | null;
  overlap: number | null;
  page_number: number | null;
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

export async function uploadDocument(
  file: File,
  config?: ChunkConfig,
  workspaceId?: number
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (config) {
    formData.append("strategy", config.strategy);
    formData.append("chunk_size", String(config.chunk_size));
    formData.append("overlap", String(config.overlap));
  }
  if (workspaceId !== undefined) {
    formData.append("workspace_id", String(workspaceId));
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

export async function listDocuments(
  status?: string,
  workspaceId?: number
): Promise<DocumentSummary[]> {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (workspaceId !== undefined) params.set("workspace_id", String(workspaceId));
  const query = params.toString();

  const response = await fetch(`${API_BASE_URL}/documents${query ? `?${query}` : ""}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Failed to list documents (status ${response.status})`);
  }
  return response.json();
}

export async function deleteDocument(documentId: number): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/documents/${documentId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `Delete failed with status ${response.status}`);
  }
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