"use client";

import { useEffect, useState } from "react";
import { useWorkspace } from "@/lib/workspace-context";
import {
  addQuestion,
  createRun,
  createSet,
  deleteQuestion,
  deleteRun,
  deleteSet,
  EvalRunDetail,
  EvalRunSummary,
  EvalSetDetail,
  EvalSetSummary,
  generateQuestions,
  getRun,
  getSet,
  listRuns,
  listSets,
  RunMetrics,
} from "@/lib/eval";
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
  Stat,
  StatusBadge,
} from "@/components/ui";

const TRANSFORMS = ["rewrite", "expand", "multi_query", "hyde"];
const CHECKBOX = "h-4 w-4 rounded border-slate-300 text-brand-600";
const TH = "px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-slate-500";
const TD = "px-3 py-2";

function metric(metrics: RunMetrics | null, key: string): string {
  const value = metrics ? metrics[key] : undefined;
  return typeof value === "number" ? value.toFixed(3) : "—";
}

/** Group "name@k" metrics into rows (metric name) by columns (k). */
function kTable(metrics: RunMetrics) {
  const rows = new Map<string, Map<number, number>>();
  const ks = new Set<number>();
  for (const [key, value] of Object.entries(metrics)) {
    const match = /^(.+)@(\d+)$/.exec(key);
    if (!match || typeof value !== "number") continue;
    const k = Number(match[2]);
    ks.add(k);
    if (!rows.has(match[1])) rows.set(match[1], new Map());
    rows.get(match[1])!.set(k, value);
  }
  return { rows: Array.from(rows.entries()), ks: Array.from(ks).sort((a, b) => a - b) };
}

export default function EvalPage() {
  const { workspaceId, workspace } = useWorkspace();
  const [sets, setSets] = useState<EvalSetSummary[]>([]);
  const [setId, setSetId] = useState<number | null>(null);
  const [detail, setDetail] = useState<EvalSetDetail | null>(null);
  const [runs, setRuns] = useState<EvalRunSummary[]>([]);
  const [openRun, setOpenRun] = useState<EvalRunDetail | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [action, setAction] = useState("");

  const [newSetName, setNewSetName] = useState("");
  const [question, setQuestion] = useState("");
  const [evidence, setEvidence] = useState("");
  const [reference, setReference] = useState("");
  const [filename, setFilename] = useState("");
  const [shouldRefuse, setShouldRefuse] = useState(false);
  const [draftCount, setDraftCount] = useState(8);

  const [mode, setMode] = useState("hybrid");
  const [rerank, setRerank] = useState(false);
  const [transforms, setTransforms] = useState<string[]>([]);
  const [generate, setGenerate] = useState(false);

  const fail = (err: unknown) => setError(err instanceof Error ? err.message : "Something went wrong");

  const refreshSets = (id: number) => listSets(id).then(setSets).catch(fail);

  useEffect(() => {
    setSets([]);
    setSetId(null);
    setMessage("");
    setError("");
    refreshSets(workspaceId);
  }, [workspaceId]);

  const refreshSet = (id: number) => {
    getSet(id).then(setDetail).catch(fail);
    listRuns(id).then(setRuns).catch(fail);
  };

  useEffect(() => {
    setDetail(null);
    setRuns([]);
    setOpenRun(null);
    if (setId !== null) refreshSet(setId);
  }, [setId]);

  const guarded = async (name: string, run: () => Promise<void>) => {
    setBusy(true);
    setAction(name);
    setError("");
    setMessage("");
    try {
      await run();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
      setAction("");
    }
  };

  const handleCreateSet = () =>
    guarded("create", async () => {
      if (!newSetName.trim()) return;
      const created = await createSet(workspaceId, newSetName.trim());
      setNewSetName("");
      await refreshSets(workspaceId);
      setSetId(created.id);
    });

  const handleAddQuestion = () =>
    guarded("add", async () => {
      if (setId === null) return;
      await addQuestion(setId, {
        question: question.trim(),
        evidence: evidence.split("\n").map((line) => line.trim()).filter(Boolean),
        reference_answer: reference.trim() || undefined,
        should_refuse: shouldRefuse,
        filename: filename.trim() || undefined,
      });
      setQuestion("");
      setEvidence("");
      setReference("");
      setFilename("");
      setShouldRefuse(false);
      refreshSet(setId);
      refreshSets(workspaceId);
    });

  const handleDraft = () =>
    guarded("draft", async () => {
      if (setId === null) return;
      const report = await generateQuestions(setId, draftCount);
      setMessage(
        `Drafted ${report.created} question(s) (${report.rejected} rejected because their quote wasn't in the text, ` +
          `${report.llm_calls} LLM call(s)). Review them: generated questions are easier than real ones.`
      );
      refreshSet(setId);
      refreshSets(workspaceId);
    });

  const questionCount = detail?.questions.length ?? 0;
  const estimatedCalls = generate ? questionCount * 2 + (transforms.length > 0 ? questionCount : 0) : transforms.length > 0 ? questionCount : 0;

  const handleRun = () =>
    guarded("run", async () => {
      if (setId === null) return;
      const run = await createRun(setId, { mode, rerank, transforms, generate });
      setMessage(`Run #${run.id} finished: ${run.status} in ${(run.elapsed_ms / 1000).toFixed(1)}s, ${run.llm_calls} LLM call(s).`);
      refreshSet(setId);
    });

  const changeMode = (value: string) => {
    setMode(value);
    if (value !== "hybrid") {
      setRerank(false);
      setTransforms([]);
      setGenerate(false);
    }
  };

  const toggleTransform = (name: string) =>
    setTransforms((current) => (current.includes(name) ? current.filter((t) => t !== name) : [...current, name]));

  const hybridOnly = mode !== "hybrid";
  const openK = openRun?.metrics ? kTable(openRun.metrics) : null;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Lab"
        title="Evaluation"
        description="A golden set is a list of questions plus the exact text that answers each one. A retrieved chunk counts as relevant when it contains that text, so the same set can score any retrieval setting and any chunking."
      />

      {error && <Alert tone="error">{error}</Alert>}
      {message && <Alert tone="success">{message}</Alert>}

      <Card
        title="Golden set"
        description={workspace?.name ? `Sets in ${workspace.name}` : undefined}
        actions={
          setId !== null && (
            <Button
              variant="danger"
              size="sm"
              loading={action === "delete-set"}
              disabled={busy}
              onClick={() =>
                guarded("delete-set", async () => {
                  await deleteSet(setId);
                  setSetId(null);
                  await refreshSets(workspaceId);
                })
              }
            >
              Delete set
            </Button>
          )
        }
      >
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Golden set">
            <select
              value={setId ?? ""}
              onChange={(e) => setSetId(e.target.value ? Number(e.target.value) : null)}
              className={inputClass}
            >
              <option value="">— choose —</option>
              {sets.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.question_count})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Create a new set">
            <div className="flex gap-2">
              <input
                value={newSetName}
                onChange={(e) => setNewSetName(e.target.value)}
                placeholder="New golden set name"
                className={inputClass}
              />
              <Button onClick={handleCreateSet} disabled={busy || !newSetName.trim()} loading={action === "create"}>
                Create
              </Button>
            </div>
          </Field>
        </div>
      </Card>

      {!detail && (
        <EmptyState
          title={sets.length === 0 ? "No golden sets in this workspace" : "No golden set selected"}
          description={
            sets.length === 0
              ? "Create a golden set above, then add questions or draft them from your documents."
              : "Choose a golden set above to edit its questions and run evaluations."
          }
        />
      )}

      {detail && (
        <>
          <div className="grid gap-6 lg:grid-cols-3">
            <Card title={`Questions (${detail.questions.length})`} className="lg:col-span-2" padded={false}>
              {detail.questions.length === 0 ? (
                <div className="p-5">
                  <EmptyState title="No questions yet." description="Add one on the right, or draft questions from this workspace's text." />
                </div>
              ) : (
                <ul className="max-h-[32rem] divide-y divide-slate-100 overflow-y-auto">
                  {detail.questions.map((q) => (
                    <li key={q.id} className="flex justify-between gap-3 px-5 py-3 text-xs">
                      <div className="min-w-0 space-y-1">
                        <p className="flex flex-wrap items-center gap-1.5 text-sm font-medium text-slate-900">
                          {q.question}
                          {q.should_refuse && <Badge tone="warning">should be refused</Badge>}
                          {q.source === "generated" && <Badge>drafted</Badge>}
                        </p>
                        {q.evidence.map((e, i) => (
                          <p key={i} className="text-slate-600">
                            evidence: “{e}”
                          </p>
                        ))}
                        {q.filename && <p className="text-slate-500">file: {q.filename}</p>}
                        {q.reference_answer && <p className="text-slate-500">reference: {q.reference_answer}</p>}
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="self-start text-red-600 hover:text-red-700"
                        aria-label="Delete question"
                        disabled={busy}
                        onClick={() => guarded("delete-q", async () => { await deleteQuestion(q.id); refreshSet(detail.id); })}
                      >
                        ✕
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <div className="space-y-6">
              <Card title="Add a question">
                <div className="space-y-3">
                  <Field label="Question">
                    <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Question" className={inputClass} />
                  </Field>
                  <Field label="Evidence" hint="One per line. Leave empty for refusal questions.">
                    <textarea
                      value={evidence}
                      onChange={(e) => setEvidence(e.target.value)}
                      rows={2}
                      placeholder="Evidence: a short exact phrase from the document that answers it (one per line)"
                      className={inputClass}
                    />
                  </Field>
                  <Field label="Reference answer">
                    <input
                      value={reference}
                      onChange={(e) => setReference(e.target.value)}
                      placeholder="Reference answer (optional, used to grade answers)"
                      className={inputClass}
                    />
                  </Field>
                  <Field label="File filter">
                    <input
                      value={filename}
                      onChange={(e) => setFilename(e.target.value)}
                      placeholder="Only count this file (optional)"
                      className={inputClass}
                    />
                  </Field>
                  <label className="flex items-start gap-2 text-xs text-slate-700">
                    <input type="checkbox" className={cx(CHECKBOX, "mt-0.5")} checked={shouldRefuse} onChange={(e) => setShouldRefuse(e.target.checked)} />
                    The documents do NOT answer this (the system should refuse; leave evidence empty)
                  </label>
                  <Button onClick={handleAddQuestion} disabled={busy || !question.trim()} loading={action === "add"} className="w-full">
                    Add question
                  </Button>
                </div>
              </Card>

              <Card title="Draft questions" description="Draft questions from this workspace's text.">
                <div className="space-y-3">
                  <div className="flex items-end gap-2">
                    <Field label="Count" className="w-24">
                      <input
                        type="number"
                        min={1}
                        max={20}
                        value={draftCount}
                        onChange={(e) => setDraftCount(Number(e.target.value))}
                        className={inputClass}
                      />
                    </Field>
                    <Button variant="secondary" onClick={handleDraft} disabled={busy} loading={action === "draft"}>
                      Draft
                    </Button>
                  </div>
                  <Alert tone="warning">Uses ~{Math.ceil(draftCount / 4)} LLM calls.</Alert>
                </div>
              </Card>
            </div>
          </div>

          <Card title="Run an evaluation">
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
                <div>
                  <span className="mb-1.5 block text-sm font-medium text-slate-700">Retrieval</span>
                  <Segmented
                    options={[
                      { value: "dense", label: "dense" },
                      { value: "sparse", label: "sparse (keywords)" },
                      { value: "hybrid", label: "hybrid" },
                    ]}
                    value={mode}
                    onChange={changeMode}
                  />
                </div>
                <div className={cx("flex flex-wrap items-center gap-4 text-sm text-slate-700", hybridOnly && "opacity-40")}>
                  <label className="flex items-center gap-2">
                    <input type="checkbox" className={CHECKBOX} disabled={hybridOnly} checked={rerank} onChange={(e) => setRerank(e.target.checked)} /> rerank
                  </label>
                  {TRANSFORMS.map((t) => (
                    <label key={t} className="flex items-center gap-2">
                      <input type="checkbox" className={CHECKBOX} disabled={hybridOnly} checked={transforms.includes(t)} onChange={() => toggleTransform(t)} /> {t}
                    </label>
                  ))}
                  <label className="flex items-center gap-2">
                    <input type="checkbox" className={CHECKBOX} disabled={hybridOnly} checked={generate} onChange={(e) => setGenerate(e.target.checked)} /> also grade answers
                  </label>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <Button onClick={handleRun} disabled={busy || questionCount === 0} loading={action === "run"}>
                  {action === "run" ? "Running..." : "Run"}
                </Button>
                {estimatedCalls === 0 ? (
                  <span className="text-xs text-slate-500">No LLM calls.</span>
                ) : (
                  <Alert tone="warning" className="flex-1">
                    Up to {estimatedCalls} LLM calls (capped at 60 per run).
                  </Alert>
                )}
              </div>
            </div>
          </Card>

          <Card
            title="Runs"
            description="Click a run to see every question, what was retrieved, and which chunks matched."
            padded={false}
          >
            {runs.length === 0 ? (
              <div className="p-5">
                <EmptyState title="No runs yet." description="Configure a run above and press Run." />
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead className="border-b border-slate-200 bg-slate-50">
                    <tr>
                      <th className={TH}>#</th>
                      <th className={TH}>Setting</th>
                      <th className={TH}>Hit@5</th>
                      <th className={TH}>Recall@5</th>
                      <th className={TH}>MRR</th>
                      <th className={TH}>NDCG@5</th>
                      <th className={TH}>Faithful</th>
                      <th className={TH}>Correct</th>
                      <th className={TH}>LLM</th>
                      <th className={TH} />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {runs.map((r) => (
                      <tr
                        key={r.id}
                        className={cx("cursor-pointer tabular-nums hover:bg-slate-50", openRun?.id === r.id && "bg-brand-50/60")}
                        onClick={() => getRun(r.id).then(setOpenRun).catch(fail)}
                      >
                        <td className={TD}>{r.id}</td>
                        <td className={TD}>
                          <span className="font-medium text-slate-800">{r.label}</span>
                          {r.status !== "completed" && (
                            <span className="ml-1.5">
                              <StatusBadge status={r.status} />
                            </span>
                          )}
                        </td>
                        <td className={TD}>{metric(r.metrics, "hit@5")}</td>
                        <td className={TD}>{metric(r.metrics, "recall@5")}</td>
                        <td className={TD}>{metric(r.metrics, "mrr")}</td>
                        <td className={TD}>{metric(r.metrics, "ndcg@5")}</td>
                        <td className={TD}>{r.metrics?.generation?.faithfulness?.toFixed(2) ?? "—"}</td>
                        <td className={TD}>{r.metrics?.generation?.correctness?.toFixed(2) ?? "—"}</td>
                        <td className={TD}>{r.llm_calls}</td>
                        <td className={TD}>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-red-600 hover:text-red-700"
                            aria-label="Delete run"
                            onClick={(e) => {
                              e.stopPropagation();
                              guarded("delete-run", async () => {
                                await deleteRun(r.id);
                                if (setId !== null) refreshSet(setId);
                              });
                            }}
                          >
                            ✕
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {openRun && (
            <div className="space-y-6">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">
                  Run #{openRun.id}: {openRun.label}
                </h2>
                {openRun.metrics && (
                  <p className="mt-0.5 text-xs text-slate-500">
                    {openRun.metrics.n_answerable} scored · {openRun.metrics.n_refusal_questions} refusal question(s) ·{" "}
                    {openRun.metrics.n_errors} error(s) · retrieval {Math.round(openRun.metrics.retrieval_ms ?? 0)} ms/question
                  </p>
                )}
              </div>

              {openRun.metrics && (
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
                  <Stat label="Hit@5" value={metric(openRun.metrics, "hit@5")} />
                  <Stat label="Recall@5" value={metric(openRun.metrics, "recall@5")} />
                  <Stat label="MRR" value={metric(openRun.metrics, "mrr")} />
                  <Stat label="NDCG@5" value={metric(openRun.metrics, "ndcg@5")} />
                  <Stat label="Faithful" value={openRun.metrics.generation?.faithfulness?.toFixed(2) ?? "—"} />
                  <Stat label="Correct" value={openRun.metrics.generation?.correctness?.toFixed(2) ?? "—"} />
                </div>
              )}

              {openK && openK.rows.length > 0 && (
                <Card title="Retrieval metrics by k" padded={false}>
                  <div className="overflow-x-auto">
                    <table className="min-w-full text-sm">
                      <thead className="border-b border-slate-200 bg-slate-50">
                        <tr>
                          <th className={TH}>Metric</th>
                          {openK.ks.map((k) => (
                            <th key={k} className={TH}>
                              @{k}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 tabular-nums">
                        {openK.rows.map(([name, values]) => (
                          <tr key={name}>
                            <td className={cx(TD, "font-medium text-slate-800")}>{name}</td>
                            {openK.ks.map((k) => (
                              <td key={k} className={TD}>
                                {values.has(k) ? values.get(k)!.toFixed(3) : "—"}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              )}

              <Card title="Per-question results" padded={false}>
                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead className="border-b border-slate-200 bg-slate-50">
                      <tr>
                        <th className={TH}>Question</th>
                        <th className={TH}>Retrieval</th>
                        <th className={TH}>Answer</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 align-top">
                      {openRun.results.map((r) => (
                        <tr key={r.question_id}>
                          <td className={cx(TD, "min-w-[16rem] max-w-md")}>
                            <p className="font-medium text-slate-900">{r.question}</p>
                            {r.should_refuse && (
                              <Badge tone="warning" className="mt-1">
                                should be refused
                              </Badge>
                            )}
                            {r.error && <p className="mt-1 text-xs text-red-600">Error: {r.error}</p>}
                            {r.retrieved && (
                              <details className="mt-2 text-xs">
                                <summary className="cursor-pointer text-slate-500">Retrieved chunks ({r.retrieved.length})</summary>
                                <ol className="mt-1.5 space-y-1">
                                  {r.retrieved.map((c) => (
                                    <li
                                      key={c.chunk_id}
                                      className={cx(
                                        "rounded-md p-1.5",
                                        c.relevant ? "border border-emerald-200 bg-emerald-50" : "bg-slate-50"
                                      )}
                                    >
                                      <span className="font-mono">#{c.rank}</span> {c.filename}
                                      {c.page_number !== null ? ` p.${c.page_number}` : ""} · {c.chunk_type} — {c.snippet}
                                    </li>
                                  ))}
                                </ol>
                              </details>
                            )}
                          </td>
                          <td className={cx(TD, "whitespace-nowrap")}>
                            {!r.should_refuse && !r.error ? (
                              r.first_relevant_rank ? (
                                <Badge tone="success">First relevant chunk at rank {r.first_relevant_rank}</Badge>
                              ) : (
                                <Badge tone="danger">No relevant chunk in the top 10</Badge>
                              )
                            ) : (
                              <span className="text-slate-400">—</span>
                            )}
                          </td>
                          <td className={cx(TD, "min-w-[14rem] text-xs text-slate-700")}>
                            {r.generation ? (
                              <div className="space-y-1">
                                <p>
                                  {r.generation.skipped ? `Answer skipped: ${r.generation.skipped}` : `Answer: ${r.generation.answer ?? "—"}`}
                                </p>
                                <div className="flex flex-wrap gap-1">
                                  {r.generation.faithfulness !== null && <Badge>faithful {r.generation.faithfulness}</Badge>}
                                  {r.generation.correctness !== null && <Badge>correct {r.generation.correctness}</Badge>}
                                  {r.generation.refusal_correct !== null && (
                                    <Badge tone={r.generation.refusal_correct ? "success" : "danger"}>
                                      refusal {r.generation.refusal_correct ? "correct" : "WRONG"}
                                    </Badge>
                                  )}
                                  {r.generation.false_refusal && <Badge tone="danger">wrongly refused</Badge>}
                                </div>
                              </div>
                            ) : (
                              <span className="text-slate-400">—</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            </div>
          )}
        </>
      )}
    </div>
  );
}
