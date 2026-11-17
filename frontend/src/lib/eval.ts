const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface GenerationMetrics {
  answers_generated: number;
  skipped: number;
  faithfulness?: number;
  correctness?: number;
  false_refusal_rate?: number;
  refusal_accuracy?: number;
}

export interface RunMetrics {
  n_questions: number;
  n_answerable: number;
  n_refusal_questions: number;
  n_errors: number;
  retrieval_ms?: number;
  generation?: GenerationMetrics;
  [key: string]: number | GenerationMetrics | undefined;
}

export interface RunConfig {
  mode: string;
  rerank: boolean;
  transforms: string[];
  k: number;
  generate: boolean;
  max_llm_calls: number;
}

export interface EvalSetSummary {
  id: number;
  workspace_id: number;
  name: string;
  description: string | null;
  question_count: number;
  created_at: string | null;
}

export interface EvalQuestion {
  id: number;
  question: string;
  evidence: string[];
  reference_answer: string | null;
  should_refuse: boolean;
  filename: string | null;
  source: string;
}

export interface EvalSetDetail {
  id: number;
  workspace_id: number;
  name: string;
  description: string | null;
  questions: EvalQuestion[];
}

export interface EvalRunSummary {
  id: number;
  eval_set_id: number;
  experiment_id: number | null;
  variant_index: number | null;
  label: string;
  config: RunConfig;
  status: string;
  metrics: RunMetrics | null;
  question_count: number;
  llm_calls: number;
  elapsed_ms: number;
  error: string | null;
  created_at: string | null;
}

export interface RetrievedItem {
  rank: number;
  chunk_id: number;
  filename: string;
  page_number: number | null;
  chunk_type: string;
  score: number;
  relevant: boolean;
  matched_evidence: number[];
  snippet: string;
}

export interface GenerationDetail {
  answer: string | null;
  refused: boolean | null;
  refusal_correct: boolean | null;
  false_refusal: boolean | null;
  faithfulness: number | null;
  correctness: number | null;
  skipped: string | null;
  judge_error: string | null;
}

export interface QuestionResult {
  question_id: number;
  question: string;
  should_refuse: boolean;
  evidence: string[];
  metrics?: Record<string, number>;
  retrieval_ms?: number;
  first_relevant_rank?: number | null;
  retrieved?: RetrievedItem[];
  generation?: GenerationDetail;
  error?: string;
}

export interface EvalRunDetail extends EvalRunSummary {
  results: QuestionResult[];
}

export interface NewQuestion {
  question: string;
  evidence: string[];
  reference_answer?: string;
  should_refuse: boolean;
  filename?: string;
}

export interface GenerateReport {
  requested: number;
  sampled: number;
  created: number;
  rejected: number;
  llm_calls: number;
  failed_calls: number;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (status ${response.status})`);
  }
  return response.json();
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const listSets = (workspaceId: number) =>
  request<EvalSetSummary[]>(`/eval/sets?workspace_id=${workspaceId}`);

export const createSet = (workspaceId: number, name: string) =>
  request<EvalSetSummary>("/eval/sets", json({ workspace_id: workspaceId, name }));

export const getSet = (id: number) => request<EvalSetDetail>(`/eval/sets/${id}`);

export const deleteSet = (id: number) => request<unknown>(`/eval/sets/${id}`, { method: "DELETE" });

export const addQuestion = (setId: number, question: NewQuestion) =>
  request<EvalQuestion>(`/eval/sets/${setId}/questions`, json(question));

export const deleteQuestion = (id: number) =>
  request<unknown>(`/eval/questions/${id}`, { method: "DELETE" });

export const generateQuestions = (setId: number, count: number) =>
  request<GenerateReport>(`/eval/sets/${setId}/generate`, json({ count }));

export const createRun = (setId: number, config: Partial<RunConfig>, label?: string) =>
  request<EvalRunSummary>("/eval/runs", json({ eval_set_id: setId, config, label }));

export const listRuns = (setId: number) => request<EvalRunSummary[]>(`/eval/runs?eval_set_id=${setId}`);

export const getRun = (id: number) => request<EvalRunDetail>(`/eval/runs/${id}`);

export const deleteRun = (id: number) => request<unknown>(`/eval/runs/${id}`, { method: "DELETE" });