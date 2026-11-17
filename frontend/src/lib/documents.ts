const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
import { workspaceForUnscopedCall } from "@/lib/auth";

export interface IngestReport {
  source: string;
  pages_total: number | null;
  pages_text: number;
  pages_ocr: number;
  tables: number;
  images_ocr: number;
  images_skipped: number;
  ocr_available: boolean;
  ocr_pages_unavailable: number;
  ocr_pages_skipped_limit: number;
  ocr_images_skipped_limit: number;
  ocr_errors: number;
  notes: string[];
}

export interface UploadResponse {
  document_id: number;
  filename: string;
  status: string;
  workspace_id: number;
  ingest_report: IngestReport | null;
  /** Set when the backend queues uploads (INGEST_ASYNC): poll getJob(job_id). */
  job_id?: number | null;
}

export interface JobStatus {
  id: number;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  workspace_id: number;
  document_id: number | null;
  attempts: number;
  max_attempts: number;
  last_error: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  run_after: string | null;
  document: { id: number; filename: string; status: string; ingest_report: IngestReport | null } | null;
}

export const JOB_DONE = new Set(["succeeded", "failed", "cancelled"]);

export async function getJob(jobId: number): Promise<JobStatus> {
  const response = await fetch(`${API_BASE_URL}/jobs/${jobId}`);
  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `Could not read job ${jobId} (status ${response.status})`);
  }
  return response.json();
}

/**
 * Polls a job until it finishes. Waits 1s, then backs off to at most 5s between
 * checks; gives up after `timeoutMs` (the job keeps running on the server).
 */
export async function waitForJob(
  jobId: number,
  onUpdate?: (job: JobStatus) => void,
  timeoutMs = 15 * 60 * 1000,
  isCancelled: () => boolean = () => false
): Promise<JobStatus> {
  const started = Date.now();
  let delay = 1000;
  for (;;) {
    const job = await getJob(jobId);
    onUpdate?.(job);
    if (JOB_DONE.has(job.status)) return job;
    if (isCancelled()) return job;
    if (Date.now() - started > timeoutMs) {
      throw new Error("Still processing after a long time; check the Inspector page later");
    }
    await new Promise((resolve) => setTimeout(resolve, delay));
    delay = Math.min(5000, Math.round(delay * 1.5));
  }
}

export interface DocumentSummary {
  id: number;
  filename: string;
  status: string;
  page_count: number | null;
  source_type: string | null;
  workspace_id: number;
  uploaded_at: string | null;
  ingest_report: IngestReport | null;
}

export interface ChunkInfo {
  id: number;
  chunk_index: number;
  content: string;
  strategy: string | null;
  chunk_size: number | null;
  overlap: number | null;
  page_number: number | null;
  chunk_type: string;
  ocr_confidence: number | null;
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
  const scope = workspaceId ?? workspaceForUnscopedCall();
  if (scope !== undefined) params.set("workspace_id", String(scope));
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