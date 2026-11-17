"use client";

import { useEffect, useState } from "react";
import {
  retrieveDebug,
  RetrievalResult,
  RetrievalMode,
  TransformationInfo,
} from "@/lib/retrieval";
import { askQuestion, QueryResponse } from "@/lib/query";
import { listDocuments, DocumentSummary } from "@/lib/documents";
import { useWorkspace } from "@/lib/workspace-context";
import {
  Alert,
  Badge,
  Button,
  Card,
  cx,
  EmptyState,
  Field,
  inputClass,
  PageHeader,
  Segmented,
} from "@/components/ui";

const STRATEGIES = [
  { key: "rewrite", label: "Rewrite", hint: "clearer standalone query" },
  { key: "expand", label: "Expand", hint: "keywords/synonyms → keyword search (any term)" },
  { key: "multi_query", label: "Multi-query", hint: "paraphrases, each searched" },
  { key: "hyde", label: "HyDE", hint: "search with a hypothetical answer" },
];

const CHECKBOX = "h-4 w-4 rounded border-slate-300 text-brand-600";

function RankChange({ before, after }: { before: number; after: number }) {
  const arrow = before > after ? "▲" : before < after ? "▼" : "=";
  const tone = before > after ? "success" : before < after ? "danger" : "neutral";
  return (
    <Badge tone={tone}>
      {arrow} was #{before} → now #{after}
    </Badge>
  );
}

function Score({ label, value }: { label: string; value: string }) {
  return (
    <Badge className="font-mono">
      <span className="mr-1 text-slate-500">{label}</span>
      {value}
    </Badge>
  );
}

function TransformationPanel({ info }: { info: TransformationInfo }) {
  return (
    <Card
      title="Query transformation"
      description={`${info.requested.join(", ")} · ${Math.round(info.elapsed_ms)} ms`}
    >
      <div className="space-y-3 text-sm text-slate-700">
        {info.fallback_used && (
          <Alert tone="warning">
            Transformation failed — only the original query was searched.
            {info.error ? ` (${info.error})` : ""}
          </Alert>
        )}

        <dl className="space-y-2">
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Original</dt>
            <dd>{info.original}</dd>
          </div>
          {info.rewrite && (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Rewrite</dt>
              <dd>{info.rewrite}</dd>
            </div>
          )}
          {info.keywords.length > 0 && (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Keywords</dt>
              <dd className="mt-1 flex flex-wrap gap-1">
                {info.keywords.map((kw, i) => (
                  <Badge key={i} tone="brand">
                    {kw}
                  </Badge>
                ))}
              </dd>
            </div>
          )}
          {info.variants.length > 0 && (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Variants</dt>
              <dd>
                <ul className="list-inside list-disc">
                  {info.variants.map((v, i) => (
                    <li key={i}>{v}</li>
                  ))}
                </ul>
              </dd>
            </div>
          )}
          {info.hyde && (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Hypothetical passage</dt>
              <dd className="mt-1 whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm leading-6">{info.hyde}</dd>
            </div>
          )}
        </dl>
        <p className="text-xs text-slate-500">
          Searches run:{" "}
          {info.jobs
            .map(
              (j) =>
                `${j.label} (${[j.dense && "dense", j.sparse && "sparse"]
                  .filter(Boolean)
                  .join("+")})`
            )
            .join(" · ")}
        </p>
      </div>
    </Card>
  );
}

export default function RetrievalLabPage() {
  const { workspaceId } = useWorkspace();
  const [question, setQuestion] = useState("");
  const [k, setK] = useState(5);
  const [threshold, setThreshold] = useState(0.8);
  const [mode, setMode] = useState<RetrievalMode>("hybrid");
  const [rerank, setRerank] = useState(false);
  const [transforms, setTransforms] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [results, setResults] = useState<RetrievalResult[] | null>(null);
  const [transformation, setTransformation] = useState<TransformationInfo | null>(null);
  const [answer, setAnswer] = useState<QueryResponse | null>(null);
  const [runFullAnswer, setRunFullAnswer] = useState(false);
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);

  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);

  useEffect(() => {
    let cancelled = false;
    setDocuments([]);
    setSelectedIds([]);
    setResults(null);
    setTransformation(null);
    setAnswer(null);
    setElapsedMs(null);
    listDocuments("processed", workspaceId)
      .then((docs) => {
        if (!cancelled) setDocuments(docs);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  const toggleDocument = (id: number) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const toggleTransform = (key: string) => {
    setTransforms((prev) =>
      prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key]
    );
  };

  const activeTransforms = mode === "hybrid" ? transforms : [];

  const runRetrieval = async () => {
    if (!question.trim()) return;
    setLoading(true);
    setError("");
    setResults(null);
    setTransformation(null);
    setAnswer(null);
    setElapsedMs(null);

    try {
      const started = performance.now();
      const debugResult = await retrieveDebug(
        question,
        k,
        threshold,
        mode,
        selectedIds,
        mode === "hybrid" && rerank,
        activeTransforms
      );
      setElapsedMs(performance.now() - started);
      setResults(debugResult.results);
      setTransformation(debugResult.transformation);

      if (runFullAnswer) {
        // same strategies as the debug run, so the comparison is fair
        const qa = await askQuestion(question, selectedIds, activeTransforms);
        setAnswer(qa);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Retrieval failed");
    } finally {
      setLoading(false);
    }
  };

  // For dense mode only, re-flag inclusion live as the threshold slider
  // moves, without re-querying — distances are already in hand.
  const displayResults = results?.map((r) => ({
    ...r,
    above_threshold:
      mode === "dense" && r.dense_distance !== null
        ? r.dense_distance <= threshold
        : r.above_threshold,
  }));

  const hybrid = mode === "hybrid";

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Lab"
        title="Retrieval Laboratory"
        description="Compare Dense, Sparse (PostgreSQL full-text), and Hybrid retrieval — then add query transformation and a cross-encoder reranker and see what each one changes."
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-1">
          <Card title="Query & settings">
            <div className="space-y-4">
              <Field label="Question">
                <textarea
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder="Type a question to debug retrieval for..."
                  className={inputClass}
                  rows={3}
                />
              </Field>

              <div>
                <span className="mb-1.5 block text-sm font-medium text-slate-700">Mode</span>
                <Segmented<RetrievalMode>
                  options={[
                    { value: "dense", label: "Dense" },
                    { value: "sparse", label: "Sparse" },
                    { value: "hybrid", label: "Hybrid" },
                  ]}
                  value={mode}
                  onChange={setMode}
                />
              </div>

              <label className={cx("flex items-center gap-2 text-sm text-slate-700", !hybrid && "opacity-40")}>
                <input
                  type="checkbox"
                  className={CHECKBOX}
                  checked={rerank}
                  disabled={!hybrid}
                  onChange={(e) => setRerank(e.target.checked)}
                />
                Rerank with cross-encoder (hybrid only)
              </label>

              <div className={cx("rounded-lg border border-slate-200 p-3", !hybrid && "opacity-40")}>
                <p className="mb-2 text-sm font-medium text-slate-700">Query transformation</p>
                <Alert tone="warning" className="mb-3">
                  Hybrid only — adds one LLM call.
                </Alert>
                <div className="space-y-2">
                  {STRATEGIES.map((s) => (
                    <label key={s.key} className="flex items-start gap-2 text-sm">
                      <input
                        type="checkbox"
                        className={cx(CHECKBOX, "mt-0.5")}
                        checked={transforms.includes(s.key)}
                        disabled={!hybrid}
                        onChange={() => toggleTransform(s.key)}
                      />
                      <span>
                        <span className="font-medium text-slate-800">{s.label}</span>
                        <span className="text-slate-500"> — {s.hint}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </div>

              <Field label={<>Top-k: <span className="font-semibold tabular-nums">{k}</span></>}>
                <input
                  type="range"
                  min={1}
                  max={20}
                  value={k}
                  onChange={(e) => setK(Number(e.target.value))}
                  className="block w-full accent-brand-600"
                />
              </Field>
              <Field
                label={
                  <>
                    Similarity threshold (dense mode only):{" "}
                    <span className="font-semibold tabular-nums">{threshold.toFixed(2)}</span>
                  </>
                }
                hint="Lower = stricter (more similar required)"
              >
                <input
                  type="range"
                  min={0}
                  max={1.5}
                  step={0.01}
                  value={threshold}
                  onChange={(e) => setThreshold(Number(e.target.value))}
                  className="block w-full accent-brand-600"
                />
              </Field>

              {documents.length > 0 && (
                <details className="rounded-lg border border-slate-200 p-3 text-sm">
                  <summary className="cursor-pointer font-medium text-slate-700">
                    Scope to specific documents (optional — {selectedIds.length} selected)
                  </summary>
                  <div className="mt-3 max-h-40 space-y-1.5 overflow-y-auto">
                    {documents.map((d) => (
                      <label key={d.id} className="flex items-center gap-2 text-slate-700">
                        <input
                          type="checkbox"
                          className={CHECKBOX}
                          checked={selectedIds.includes(d.id)}
                          onChange={() => toggleDocument(d.id)}
                        />
                        <span className="truncate">
                          #{d.id} — {d.filename}
                        </span>
                      </label>
                    ))}
                  </div>
                </details>
              )}

              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  className={CHECKBOX}
                  checked={runFullAnswer}
                  onChange={(e) => setRunFullAnswer(e.target.checked)}
                />
                Also run full answer (calls the LLM) for comparison
              </label>

              <Button onClick={runRetrieval} disabled={!question.trim()} loading={loading} className="w-full">
                {loading
                  ? "Retrieving..."
                  : `Run ${mode[0].toUpperCase()}${mode.slice(1)} Retrieval${
                      activeTransforms.length > 0 ? " + Transform" : ""
                    }${hybrid && rerank ? " + Rerank" : ""}`}
              </Button>
            </div>
          </Card>
        </div>

        <div className="space-y-6 lg:col-span-2">
          {error && <Alert tone="error">{error}</Alert>}

          {transformation && <TransformationPanel info={transformation} />}

          {answer && (
            <Card
              title="Full answer"
              description="From /query, same transformations; reranked if enabled on the server."
            >
              <p className="whitespace-pre-wrap text-sm leading-6 text-slate-800">{answer.answer}</p>
              {answer.transformation_fallback && (
                <Alert tone="warning" className="mt-3">
                  Transformation fell back to the original query for this answer.
                </Alert>
              )}
            </Card>
          )}

          {displayResults ? (
            <Card
              title={`${displayResults.length} candidate(s) retrieved`}
              description={elapsedMs !== null ? `${Math.round(elapsedMs)} ms` : undefined}
              padded={false}
            >
              {displayResults.length === 0 ? (
                <div className="p-5">
                  <EmptyState title="No candidates" description="Try another question, mode or a looser threshold." />
                </div>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {displayResults.map((r, i) => (
                    <li
                      key={r.chunk_id}
                      className={cx("space-y-2 px-5 py-4 text-sm", !r.above_threshold && "opacity-60")}
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={cx(
                            "inline-flex h-6 min-w-[1.5rem] items-center justify-center rounded-md px-1.5 text-xs font-semibold tabular-nums",
                            r.above_threshold ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-600"
                          )}
                        >
                          #{i + 1}
                        </span>
                        <span className="min-w-0 truncate font-medium text-slate-800">{r.filename}</span>
                        {r.page_number !== null && <span className="text-xs text-slate-500">page {r.page_number}</span>}
                        {mode === "dense" && (
                          <Badge tone={r.above_threshold ? "success" : "neutral"}>
                            {r.above_threshold ? "✓ included" : "✗ excluded"}
                          </Badge>
                        )}
                      </div>
                      <div className="flex flex-wrap items-center gap-1.5">
                        {r.dense_distance !== null && <Score label="dist" value={r.dense_distance.toFixed(3)} />}
                        {r.sparse_score !== null && <Score label="fts" value={r.sparse_score.toFixed(3)} />}
                        {r.rrf_score !== null && <Score label="rrf" value={r.rrf_score.toFixed(4)} />}
                        {r.rerank_score !== null && <Score label="rerank" value={r.rerank_score.toFixed(3)} />}
                        {r.pre_rerank_rank !== null && r.post_rerank_rank !== null && (
                          <RankChange before={r.pre_rerank_rank} after={r.post_rerank_rank} />
                        )}
                        {r.found_by.length > 0 && (
                          <span className="text-xs text-slate-500">found by: {r.found_by.join(" + ")}</span>
                        )}
                      </div>
                      {r.found_by_queries.length > 0 && (
                        <p className="text-xs text-brand-700">surfaced by → {r.found_by_queries.join(" · ")}</p>
                      )}
                      <details className="group rounded-lg bg-slate-50 p-3">
                        <summary className="cursor-pointer list-none text-sm leading-6 text-slate-700">
                          <span className="line-clamp-3 group-open:hidden">{r.content}</span>
                          <span className="mt-1 block text-xs font-medium text-brand-600 group-open:hidden">Show full chunk</span>
                          <span className="hidden text-xs font-medium text-brand-600 group-open:block">Collapse</span>
                        </summary>
                        <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-slate-700">{r.content}</p>
                      </details>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          ) : (
            !transformation &&
            !answer && (
              <EmptyState
                title="No retrieval run yet"
                description="Type a question, choose a mode and run retrieval to inspect candidates and their scores."
              />
            )
          )}
        </div>
      </div>
    </div>
  );
}
