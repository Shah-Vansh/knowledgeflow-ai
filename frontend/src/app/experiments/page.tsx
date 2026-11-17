"use client";

import { useEffect, useState } from "react";
import { listWorkspaces, Workspace } from "@/lib/workspaces";
import { EvalSetSummary, listSets } from "@/lib/eval";
import {
  Comparison,
  ComparisonRow,
  createExperiment,
  deleteExperiment,
  Delta,
  ExperimentSummary,
  getExperiment,
  listExperiments,
  runVariant,
} from "@/lib/experiments";

const PRESETS: Record<string, unknown[]> = {
  "Retrieval ablation": [
    { label: "dense only", mode: "dense" },
    { label: "keywords only", mode: "sparse" },
    { label: "hybrid", mode: "hybrid" },
    { label: "hybrid + rerank", mode: "hybrid", rerank: true },
  ],
  "Query transforms": [
    { label: "hybrid + rerank (baseline)", mode: "hybrid", rerank: true },
    { label: "+ rewrite", mode: "hybrid", rerank: true, transforms: ["rewrite"] },
    { label: "+ expand", mode: "hybrid", rerank: true, transforms: ["expand"] },
    { label: "+ multi_query", mode: "hybrid", rerank: true, transforms: ["multi_query"] },
    { label: "+ hyde", mode: "hybrid", rerank: true, transforms: ["hyde"] },
  ],
  Chunking: [
    { label: "fixed 500, no overlap", mode: "hybrid", chunking: { strategy: "fixed_size", chunk_size: 500, overlap: 0 } },
    { label: "fixed 500, overlap 100", mode: "hybrid", chunking: { strategy: "fixed_size", chunk_size: 500, overlap: 100 } },
    { label: "sentence 500", mode: "hybrid", chunking: { strategy: "sentence", chunk_size: 500, overlap: 0 } },
    { label: "recursive 1000", mode: "hybrid", chunking: { strategy: "recursive", chunk_size: 1000, overlap: 0 } },
  ],
};

const COLUMNS: { key: string; label: string }[] = [
  { key: "hit@5", label: "Hit@5" },
  { key: "recall@5", label: "Recall@5" },
  { key: "mrr", label: "MRR" },
  { key: "ndcg@5", label: "NDCG@5" },
  { key: "faithfulness", label: "Faithful" },
  { key: "correctness", label: "Correct" },
];

function value(row: ComparisonRow, key: string): number | undefined {
  if (!row.metrics) return undefined;
  if (key === "faithfulness" || key === "correctness") return row.metrics.generation?.[key];
  const raw = row.metrics[key];
  return typeof raw === "number" ? raw : undefined;
}

function DeltaText({ delta }: { delta: Delta | undefined }) {
  if (!delta) return null;
  const color = !delta.significant ? "text-gray-400" : delta.mean > 0 ? "text-green-700" : "text-red-600";
  const sign = delta.mean > 0 ? "+" : "";
  return (
    <span className={`block ${color}`} title={`95% interval ${delta.ci_low.toFixed(3)} to ${delta.ci_high.toFixed(3)} over ${delta.n} questions`}>
      {sign}{delta.mean.toFixed(3)} {delta.significant ? "✓" : ""}
    </span>
  );
}

export default function ExperimentsPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<number | null>(null);
  const [sets, setSets] = useState<EvalSetSummary[]>([]);
  const [setId, setSetId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [preset, setPreset] = useState("Retrieval ablation");
  const [variantsText, setVariantsText] = useState(JSON.stringify(PRESETS["Retrieval ablation"], null, 2));
  const [experiments, setExperiments] = useState<ExperimentSummary[]>([]);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [progress, setProgress] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const fail = (err: unknown) => setError(err instanceof Error ? err.message : "Something went wrong");

  useEffect(() => {
    listWorkspaces()
      .then((list) => {
        setWorkspaces(list);
        if (list.length > 0) setWorkspaceId(list[0].id);
      })
      .catch(fail);
    listExperiments().then(setExperiments).catch(fail);
  }, []);

  useEffect(() => {
    if (workspaceId === null) return;
    setSetId(null);
    listSets(workspaceId).then(setSets).catch(fail);
  }, [workspaceId]);

  const choosePreset = (key: string) => {
    setPreset(key);
    if (PRESETS[key]) setVariantsText(JSON.stringify(PRESETS[key], null, 2));
  };

  const handleCreateAndRun = async () => {
    if (setId === null || !name.trim()) return;
    let variants: unknown[];
    try {
      const parsed: unknown = JSON.parse(variantsText);
      if (!Array.isArray(parsed)) throw new Error("The variants must be a JSON list");
      variants = parsed;
    } catch (err) {
      setError(err instanceof Error ? `Variants JSON: ${err.message}` : "Invalid JSON");
      return;
    }

    setBusy(true);
    setError("");
    setErrors([]);
    try {
      const created = await createExperiment(setId, name.trim(), variants);
      const id = created.experiment.id;
      setComparison(created);
      const failures: string[] = [];

      for (let index = 0; index < created.variants.length; index++) {
        setProgress(`Running ${index + 1} of ${created.variants.length}: ${created.variants[index].label}`);
        try {
          await runVariant(id, index);
        } catch (err) {
          failures.push(`${created.variants[index].label}: ${err instanceof Error ? err.message : "failed"}`);
        }
        setComparison(await getExperiment(id));
      }

      setErrors(failures);
      setProgress("");
      setName("");
      setExperiments(await listExperiments());
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
      setProgress("");
    }
  };

  const open = (id: number) => getExperiment(id).then(setComparison).catch(fail);

  const maxMrr = Math.max(0.0001, ...(comparison?.variants.map((v) => value(v, "mrr") ?? 0) ?? [0]));

  return (
    <main className="min-h-screen p-8 flex flex-col items-center">
      <h1 className="text-2xl font-bold mb-2">Experiments</h1>
      <p className="text-sm text-gray-500 mb-6 text-center max-w-2xl">
        Compare settings on the same golden set. The first variant is the baseline; every other one is
        compared with it question by question. Grey differences are within chance, and ✓ means the 95%
        interval excludes zero. With a small set, expect few ✓.
      </p>

      <div className="w-full max-w-5xl space-y-5">
        {error && <div className="text-red-600 text-sm">{error}</div>}

        <section className="border border-gray-300 rounded-lg bg-white p-4 space-y-3">
          <h2 className="font-semibold text-sm">New experiment</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="block text-sm">
              Workspace
              <select value={workspaceId ?? ""} onChange={(e) => setWorkspaceId(Number(e.target.value))}
                className="block w-full border border-gray-300 rounded p-2 mt-1">
                {workspaces.map((w) => (<option key={w.id} value={w.id}>{w.name}</option>))}
              </select>
            </label>
            <label className="block text-sm">
              Golden set
              <select value={setId ?? ""} onChange={(e) => setSetId(e.target.value ? Number(e.target.value) : null)}
                className="block w-full border border-gray-300 rounded p-2 mt-1">
                <option value="">— choose —</option>
                {sets.map((s) => (<option key={s.id} value={s.id}>{s.name} ({s.question_count})</option>))}
              </select>
            </label>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Experiment name"
              className="border border-gray-300 rounded p-2 text-sm" />
            <select value={preset} onChange={(e) => choosePreset(e.target.value)} className="border border-gray-300 rounded p-2 text-sm">
              {Object.keys(PRESETS).map((key) => (<option key={key} value={key}>{key}</option>))}
            </select>
          </div>
          <label className="block text-xs text-gray-600">
            Variants (editable JSON). Allowed fields: label, mode (dense|sparse|hybrid), rerank, transforms, generate, and chunking {"{strategy, chunk_size, overlap}"}.
            Chunking variants re-chunk your documents into a temporary copy; the real data is never changed.
            <textarea value={variantsText} onChange={(e) => setVariantsText(e.target.value)} rows={9}
              className="w-full border border-gray-300 rounded p-2 font-mono text-xs mt-1" />
          </label>
          <button onClick={handleCreateAndRun} disabled={busy || setId === null || !name.trim()}
            className="bg-blue-600 text-white rounded px-4 py-2 text-sm disabled:opacity-50">
            {busy ? progress || "Working..." : "Create and run all variants"}
          </button>
          {errors.length > 0 && (
            <ul className="text-xs text-red-600 list-disc list-inside">
              {errors.map((e, i) => (<li key={i}>{e}</li>))}
            </ul>
          )}
        </section>

        {comparison && (
          <section className="border border-gray-300 rounded-lg bg-white p-4 space-y-3 overflow-x-auto">
            <h2 className="font-semibold text-sm">{comparison.experiment.name}</h2>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left border-b border-gray-200">
                  <th className="py-1 pr-3">Variant</th>
                  {COLUMNS.map((c) => (<th key={c.key} className="pr-3">{c.label}</th>))}
                  <th className="pr-3">Retrieval ms</th>
                  <th className="pr-3">LLM calls</th>
                  <th>MRR</th>
                </tr>
              </thead>
              <tbody>
                {comparison.variants.map((row) => (
                  <tr key={row.index} className="border-b border-gray-100 align-top">
                    <td className="py-1 pr-3 font-medium">
                      {row.label}
                      {row.index === 0 && <span className="ml-1 text-gray-400 font-normal">(baseline)</span>}
                    </td>
                    {COLUMNS.map((c) => {
                      const v = value(row, c.key);
                      return (
                        <td key={c.key} className="pr-3">
                          {v === undefined ? (row.run_id === null ? "…" : "—") : v.toFixed(3)}
                          <DeltaText delta={row.delta_vs_baseline?.[c.key]} />
                        </td>
                      );
                    })}
                    <td className="pr-3">{row.metrics?.retrieval_ms !== undefined ? Math.round(row.metrics.retrieval_ms) : "—"}</td>
                    <td className="pr-3">{row.run_id === null ? "—" : row.llm_calls}</td>
                    <td className="w-32">
                      <div className="h-3 bg-blue-500 rounded" style={{ width: `${((value(row, "mrr") ?? 0) / maxMrr) * 100}%` }} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-gray-400">
              Hover a difference to see its 95% interval. Scores computed on generated questions are optimistic.
            </p>
          </section>
        )}

        <section className="border border-gray-300 rounded-lg bg-white p-4 space-y-2">
          <h2 className="font-semibold text-sm">Past experiments</h2>
          {experiments.length === 0 && <p className="text-xs text-gray-500">None yet.</p>}
          {experiments.map((e) => (
            <div key={e.id} className="flex items-center justify-between text-sm border border-gray-200 rounded p-2">
              <button className="text-left text-blue-600 underline" onClick={() => open(e.id)}>
                #{e.id} {e.name} <span className="text-gray-500 no-underline">· {e.variant_count} variants</span>
              </button>
              <button className="text-red-600 text-xs"
                onClick={() => deleteExperiment(e.id).then(() => { setComparison(null); return listExperiments().then(setExperiments); }).catch(fail)}>
                Delete
              </button>
            </div>
          ))}
        </section>

        <div className="flex justify-between text-sm pt-2">
          <a href="/eval" className="text-blue-600 underline">← Evaluation</a>
          <a href="/chat" className="text-blue-600 underline">Chat →</a>
        </div>
      </div>
    </main>
  );
}