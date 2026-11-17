"use client";

import { useEffect, useState } from "react";
import { listWorkspaces, Workspace } from "@/lib/workspaces";
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

const TRANSFORMS = ["rewrite", "expand", "multi_query", "hyde"];

function metric(metrics: RunMetrics | null, key: string): string {
  const value = metrics ? metrics[key] : undefined;
  return typeof value === "number" ? value.toFixed(3) : "—";
}

export default function EvalPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<number | null>(null);
  const [sets, setSets] = useState<EvalSetSummary[]>([]);
  const [setId, setSetId] = useState<number | null>(null);
  const [detail, setDetail] = useState<EvalSetDetail | null>(null);
  const [runs, setRuns] = useState<EvalRunSummary[]>([]);
  const [openRun, setOpenRun] = useState<EvalRunDetail | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

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

  useEffect(() => {
    listWorkspaces()
      .then((list) => {
        setWorkspaces(list);
        if (list.length > 0) setWorkspaceId(list[0].id);
      })
      .catch(fail);
  }, []);

  const refreshSets = (id: number) => listSets(id).then(setSets).catch(fail);

  useEffect(() => {
    if (workspaceId === null) return;
    setSetId(null);
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

  const guarded = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const handleCreateSet = () =>
    guarded(async () => {
      if (workspaceId === null || !newSetName.trim()) return;
      const created = await createSet(workspaceId, newSetName.trim());
      setNewSetName("");
      await refreshSets(workspaceId);
      setSetId(created.id);
    });

  const handleAddQuestion = () =>
    guarded(async () => {
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
      if (workspaceId !== null) refreshSets(workspaceId);
    });

  const handleDraft = () =>
    guarded(async () => {
      if (setId === null) return;
      const report = await generateQuestions(setId, draftCount);
      setMessage(
        `Drafted ${report.created} question(s) (${report.rejected} rejected because their quote wasn't in the text, ` +
          `${report.llm_calls} LLM call(s)). Review them: generated questions are easier than real ones.`
      );
      refreshSet(setId);
      if (workspaceId !== null) refreshSets(workspaceId);
    });

  const questionCount = detail?.questions.length ?? 0;
  const estimatedCalls = generate ? questionCount * 2 + (transforms.length > 0 ? questionCount : 0) : transforms.length > 0 ? questionCount : 0;

  const handleRun = () =>
    guarded(async () => {
      if (setId === null) return;
      const run = await createRun(setId, { mode, rerank, transforms, generate });
      setMessage(`Run #${run.id} finished: ${run.status} in ${(run.elapsed_ms / 1000).toFixed(1)}s, ${run.llm_calls} LLM call(s).`);
      refreshSet(setId);
    });

  const toggleTransform = (name: string) =>
    setTransforms((current) => (current.includes(name) ? current.filter((t) => t !== name) : [...current, name]));

  const hybridOnly = mode !== "hybrid";

  return (
    <main className="min-h-screen p-8 flex flex-col items-center">
      <h1 className="text-2xl font-bold mb-2">Evaluation</h1>
      <p className="text-sm text-gray-500 mb-6 text-center max-w-2xl">
        A golden set is a list of questions plus the exact text that answers each one. A retrieved chunk
        counts as relevant when it contains that text, so the same set can score any retrieval setting
        and any chunking.
      </p>

      <div className="w-full max-w-5xl space-y-5">
        {error && <div className="text-red-600 text-sm">{error}</div>}
        {message && <div className="text-green-700 text-sm bg-green-50 border border-green-200 rounded p-2">{message}</div>}

        <section className="border border-gray-300 rounded-lg bg-white p-4 space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="block text-sm">
              Workspace
              <select
                value={workspaceId ?? ""}
                onChange={(e) => setWorkspaceId(Number(e.target.value))}
                className="block w-full border border-gray-300 rounded p-2 mt-1"
              >
                {workspaces.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              Golden set
              <select
                value={setId ?? ""}
                onChange={(e) => setSetId(e.target.value ? Number(e.target.value) : null)}
                className="block w-full border border-gray-300 rounded p-2 mt-1"
              >
                <option value="">— choose —</option>
                {sets.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.question_count})
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="flex gap-2">
            <input
              value={newSetName}
              onChange={(e) => setNewSetName(e.target.value)}
              placeholder="New golden set name"
              className="flex-1 border border-gray-300 rounded p-2 text-sm"
            />
            <button
              onClick={handleCreateSet}
              disabled={busy || !newSetName.trim()}
              className="bg-blue-600 text-white rounded px-4 text-sm disabled:opacity-50"
            >
              Create
            </button>
            {setId !== null && (
              <button
                onClick={() =>
                  guarded(async () => {
                    await deleteSet(setId);
                    setSetId(null);
                    if (workspaceId !== null) await refreshSets(workspaceId);
                  })
                }
                className="border border-red-300 text-red-600 rounded px-3 text-sm"
              >
                Delete set
              </button>
            )}
          </div>
        </section>

        {detail && (
          <>
            <section className="border border-gray-300 rounded-lg bg-white p-4 space-y-3">
              <h2 className="font-semibold text-sm">Questions ({detail.questions.length})</h2>
              {detail.questions.length === 0 && <p className="text-xs text-gray-500">No questions yet.</p>}
              <ul className="space-y-2">
                {detail.questions.map((q) => (
                  <li key={q.id} className="text-xs border border-gray-200 rounded p-2 flex justify-between gap-3">
                    <div className="space-y-0.5">
                      <p className="font-medium text-sm">
                        {q.question}{" "}
                        {q.should_refuse && <span className="text-amber-700 text-xs">(should be refused)</span>}
                        {q.source === "generated" && <span className="text-gray-400 text-xs"> · drafted</span>}
                      </p>
                      {q.evidence.map((e, i) => (
                        <p key={i} className="text-gray-600">
                          evidence: “{e}”
                        </p>
                      ))}
                      {q.filename && <p className="text-gray-500">file: {q.filename}</p>}
                      {q.reference_answer && <p className="text-gray-500">reference: {q.reference_answer}</p>}
                    </div>
                    <button
                      onClick={() => guarded(async () => { await deleteQuestion(q.id); refreshSet(detail.id); })}
                      className="text-red-600 self-start"
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>

              <div className="border-t border-gray-200 pt-3 space-y-2">
                <h3 className="text-sm font-medium">Add a question</h3>
                <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Question"
                  className="w-full border border-gray-300 rounded p-2 text-sm" />
                <textarea value={evidence} onChange={(e) => setEvidence(e.target.value)} rows={2}
                  placeholder="Evidence: a short exact phrase from the document that answers it (one per line)"
                  className="w-full border border-gray-300 rounded p-2 text-sm" />
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  <input value={reference} onChange={(e) => setReference(e.target.value)} placeholder="Reference answer (optional, used to grade answers)"
                    className="border border-gray-300 rounded p-2 text-sm" />
                  <input value={filename} onChange={(e) => setFilename(e.target.value)} placeholder="Only count this file (optional)"
                    className="border border-gray-300 rounded p-2 text-sm" />
                </div>
                <label className="text-xs flex items-center gap-2">
                  <input type="checkbox" checked={shouldRefuse} onChange={(e) => setShouldRefuse(e.target.checked)} />
                  The documents do NOT answer this (the system should refuse; leave evidence empty)
                </label>
                <button onClick={handleAddQuestion} disabled={busy || !question.trim()}
                  className="bg-blue-600 text-white rounded px-4 py-1.5 text-sm disabled:opacity-50">
                  Add question
                </button>
              </div>

              <div className="border-t border-gray-200 pt-3 flex items-center gap-3 text-sm">
                <span>Draft questions from this workspace&apos;s text:</span>
                <input type="number" min={1} max={20} value={draftCount} onChange={(e) => setDraftCount(Number(e.target.value))}
                  className="w-16 border border-gray-300 rounded p-1" />
                <button onClick={handleDraft} disabled={busy}
                  className="border border-blue-600 text-blue-600 rounded px-3 py-1 text-xs disabled:opacity-50">
                  Draft (~{Math.ceil(draftCount / 4)} LLM calls)
                </button>
              </div>
            </section>

            <section className="border border-gray-300 rounded-lg bg-white p-4 space-y-3">
              <h2 className="font-semibold text-sm">Run an evaluation</h2>
              <div className="flex flex-wrap items-center gap-4 text-sm">
                <label>
                  Retrieval{" "}
                  <select value={mode} onChange={(e) => { setMode(e.target.value); if (e.target.value !== "hybrid") { setRerank(false); setTransforms([]); setGenerate(false); } }}
                    className="border border-gray-300 rounded p-1">
                    <option value="dense">dense</option>
                    <option value="sparse">sparse (keywords)</option>
                    <option value="hybrid">hybrid</option>
                  </select>
                </label>
                <label className={hybridOnly ? "text-gray-400" : ""}>
                  <input type="checkbox" disabled={hybridOnly} checked={rerank} onChange={(e) => setRerank(e.target.checked)} /> rerank
                </label>
                {TRANSFORMS.map((t) => (
                  <label key={t} className={hybridOnly ? "text-gray-400" : ""}>
                    <input type="checkbox" disabled={hybridOnly} checked={transforms.includes(t)} onChange={() => toggleTransform(t)} /> {t}
                  </label>
                ))}
                <label className={hybridOnly ? "text-gray-400" : ""}>
                  <input type="checkbox" disabled={hybridOnly} checked={generate} onChange={(e) => setGenerate(e.target.checked)} /> also grade answers
                </label>
              </div>
              <div className="flex items-center gap-3">
                <button onClick={handleRun} disabled={busy || questionCount === 0}
                  className="bg-blue-600 text-white rounded px-4 py-1.5 text-sm disabled:opacity-50">
                  {busy ? "Running..." : "Run"}
                </button>
                <span className="text-xs text-gray-500">
                  {estimatedCalls === 0 ? "No LLM calls." : `Up to ${estimatedCalls} LLM calls (capped at 60 per run).`}
                </span>
              </div>
            </section>

            <section className="border border-gray-300 rounded-lg bg-white p-4 space-y-3 overflow-x-auto">
              <h2 className="font-semibold text-sm">Runs</h2>
              {runs.length === 0 && <p className="text-xs text-gray-500">No runs yet.</p>}
              {runs.length > 0 && (
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left border-b border-gray-200">
                      <th className="py-1 pr-2">#</th><th className="pr-2">Setting</th><th className="pr-2">Hit@5</th>
                      <th className="pr-2">Recall@5</th><th className="pr-2">MRR</th><th className="pr-2">NDCG@5</th>
                      <th className="pr-2">Faithful</th><th className="pr-2">Correct</th><th className="pr-2">LLM</th><th />
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((r) => (
                      <tr key={r.id} className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer"
                        onClick={() => getRun(r.id).then(setOpenRun).catch(fail)}>
                        <td className="py-1 pr-2">{r.id}</td>
                        <td className="pr-2">{r.label}{r.status !== "completed" ? ` (${r.status})` : ""}</td>
                        <td className="pr-2">{metric(r.metrics, "hit@5")}</td>
                        <td className="pr-2">{metric(r.metrics, "recall@5")}</td>
                        <td className="pr-2">{metric(r.metrics, "mrr")}</td>
                        <td className="pr-2">{metric(r.metrics, "ndcg@5")}</td>
                        <td className="pr-2">{r.metrics?.generation?.faithfulness?.toFixed(2) ?? "—"}</td>
                        <td className="pr-2">{r.metrics?.generation?.correctness?.toFixed(2) ?? "—"}</td>
                        <td className="pr-2">{r.llm_calls}</td>
                        <td>
                          <button className="text-red-600" onClick={(e) => { e.stopPropagation(); guarded(async () => { await deleteRun(r.id); if (setId !== null) refreshSet(setId); }); }}>✕</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <p className="text-xs text-gray-400">Click a run to see every question, what was retrieved, and which chunks matched.</p>
            </section>

            {openRun && (
              <section className="border border-gray-300 rounded-lg bg-white p-4 space-y-3">
                <h2 className="font-semibold text-sm">Run #{openRun.id}: {openRun.label}</h2>
                {openRun.metrics && (
                  <p className="text-xs text-gray-600">
                    {openRun.metrics.n_answerable} scored · {openRun.metrics.n_refusal_questions} refusal question(s) ·{" "}
                    {openRun.metrics.n_errors} error(s) · retrieval {Math.round(openRun.metrics.retrieval_ms ?? 0)} ms/question
                  </p>
                )}
                {openRun.results.map((r) => (
                  <div key={r.question_id} className="border border-gray-200 rounded p-2 text-xs space-y-1">
                    <p className="font-medium text-sm">{r.question}</p>
                    {r.error && <p className="text-red-600">Error: {r.error}</p>}
                    {!r.should_refuse && !r.error && (
                      <p className={r.first_relevant_rank ? "text-green-700" : "text-red-600"}>
                        {r.first_relevant_rank ? `First relevant chunk at rank ${r.first_relevant_rank}` : "No relevant chunk in the top 10"}
                      </p>
                    )}
                    {r.generation && (
                      <p className="text-gray-700">
                        {r.generation.skipped ? `Answer skipped: ${r.generation.skipped}` : `Answer: ${r.generation.answer ?? "—"}`}
                        {r.generation.faithfulness !== null && ` · faithful ${r.generation.faithfulness}`}
                        {r.generation.correctness !== null && ` · correct ${r.generation.correctness}`}
                        {r.generation.refusal_correct !== null && ` · refusal ${r.generation.refusal_correct ? "correct" : "WRONG"}`}
                        {r.generation.false_refusal && " · wrongly refused"}
                      </p>
                    )}
                    {r.retrieved && (
                      <details>
                        <summary className="cursor-pointer text-gray-500">Retrieved chunks ({r.retrieved.length})</summary>
                        <ol className="mt-1 space-y-1">
                          {r.retrieved.map((c) => (
                            <li key={c.chunk_id} className={`p-1 rounded ${c.relevant ? "bg-green-50 border border-green-200" : "bg-gray-50"}`}>
                              <span className="font-mono">#{c.rank}</span> {c.filename}
                              {c.page_number !== null ? ` p.${c.page_number}` : ""} · {c.chunk_type} — {c.snippet}
                            </li>
                          ))}
                        </ol>
                      </details>
                    )}
                  </div>
                ))}
              </section>
            )}
          </>
        )}

        <div className="flex justify-between text-sm pt-2">
          <a href="/inspector" className="text-blue-600 underline">← Inspector</a>
          <a href="/experiments" className="text-blue-600 underline">Experiments →</a>
        </div>
      </div>
    </main>
  );
}