import { RunConfig, RunMetrics } from "@/lib/eval";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Chunking {
  strategy: string;
  chunk_size: number;
  overlap: number;
}

export interface Variant extends RunConfig {
  label: string;
  chunking?: Chunking;
}

export interface Delta {
  mean: number;
  ci_low: number;
  ci_high: number;
  n: number;
  significant: boolean;
}

export interface ComparisonRow {
  index: number;
  label: string;
  config: Variant;
  run_id: number | null;
  metrics: RunMetrics | null;
  llm_calls: number;
  elapsed_ms: number | null;
  delta_vs_baseline: Record<string, Delta> | null;
}

export interface Comparison {
  experiment: {
    id: number;
    name: string;
    description: string | null;
    eval_set_id: number;
    created_at: string | null;
  };
  baseline_index: number;
  variants: ComparisonRow[];
}

export interface ExperimentSummary {
  id: number;
  name: string;
  eval_set_id: number;
  variant_count: number;
  created_at: string | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (status ${response.status})`);
  }
  return response.json();
}

export const listExperiments = () => request<ExperimentSummary[]>("/experiments");

export const getExperiment = (id: number) => request<Comparison>(`/experiments/${id}`);

export const deleteExperiment = (id: number) => request<unknown>(`/experiments/${id}`, { method: "DELETE" });

export const createExperiment = (evalSetId: number, name: string, variants: unknown[]) =>
  request<Comparison>("/experiments", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ eval_set_id: evalSetId, name, variants }),
  });

export const runVariant = (experimentId: number, index: number) =>
  request<unknown>(`/experiments/${experimentId}/run-variant`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ index }),
  });