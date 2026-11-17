"use client";

import { useEffect, useState } from "react";
import { useWorkspace } from "@/lib/workspace-context";
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
import {
  Alert,
  Badge,
  Button,
  ButtonLink,
  Card,
  cx,
  EmptyState,
  Field,
  inputClass,
  PageHeader,
} from "@/components/ui";

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

const TH = "px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-slate-500";
const TD = "px-3 py-2";

function value(row: ComparisonRow, key: string): number | undefined {
  if (!row.metrics) return undefined;
  if (key === "faithfulness" || key === "correctness") return row.metrics.generation?.[key];
  const raw = row.metrics[key];
  return typeof raw === "number" ? raw : undefined;
}

function DeltaText({ delta }: { delta: Delta | undefined }) {
  if (!delta) return null;
  const sign = delta.mean > 0 ? "+" : "";
  const title = `95% interval ${delta.ci_low.toFixed(3)} to ${delta.ci_high.toFixed(3)} over ${delta.n} questions`;
  if (!delta.significant) {
    return (
      <span className="mt-0.5 block text-xs text-slate-400" title={title}>
        {sign}
        {delta.mean.toFixed(3)}
      </span>
    );
  }
  return (
    <span className="mt-1 block" title={title}>
      <Badge tone={delta.mean > 0 ? "success" : "danger"}>
        {sign}
        {delta.mean.toFixed(3)} ✓
      </Badge>
    </span>
  );
}

export default function ExperimentsPage() {
  const { workspaceId, workspace } = useWorkspace();
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
    listExperiments().then(setExperiments).catch(fail);
  }, []);

  useEffect(() => {
    setSets([]);
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
    <div className="space-y-6">
      <PageHeader
        eyebrow="Lab"
        title="Experiments"
        description="Compare settings on the same golden set. The first variant is the baseline; every other one is compared with it question by question. Grey differences are within chance, and ✓ means the 95% interval excludes zero. With a small set, expect few ✓."
      />

      {error && <Alert tone="error">{error}</Alert>}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="New experiment" className="lg:col-span-2">
          <div className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Golden set" hint={workspace?.name ? `From ${workspace.name}` : undefined}>
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
              <Field label="Experiment name">
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Experiment name" className={inputClass} />
              </Field>
            </div>
            <Field label="Preset">
              <select value={preset} onChange={(e) => choosePreset(e.target.value)} className={inputClass}>
                {Object.keys(PRESETS).map((key) => (
                  <option key={key} value={key}>
                    {key}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label="Variants (editable JSON)"
              hint={
                <>
                  Allowed fields: label, mode (dense|sparse|hybrid), rerank, transforms, generate, and chunking{" "}
                  {"{strategy, chunk_size, overlap}"}. Chunking variants re-chunk your documents into a temporary copy;
                  the real data is never changed.
                </>
              }
            >
              <textarea
                value={variantsText}
                onChange={(e) => setVariantsText(e.target.value)}
                rows={10}
                className={cx(inputClass, "font-mono text-xs")}
              />
            </Field>
            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={handleCreateAndRun} disabled={setId === null || !name.trim()} loading={busy}>
                {busy ? progress || "Working..." : "Create and run all variants"}
              </Button>
              {sets.length === 0 && (
                <span className="text-xs text-slate-500">
                  No golden sets in this workspace yet.{" "}
                  <ButtonLink href="/eval" variant="ghost" size="sm">
                    Create one in Evaluation
                  </ButtonLink>
                </span>
              )}
            </div>
            {errors.length > 0 && (
              <Alert tone="error" title="Some variants failed">
                <ul className="list-inside list-disc text-xs">
                  {errors.map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
              </Alert>
            )}
          </div>
        </Card>

        <Card title="Past experiments" padded={false}>
          {experiments.length === 0 ? (
            <div className="p-5">
              <EmptyState title="None yet." description="Create and run an experiment to compare settings." />
            </div>
          ) : (
            <ul className="max-h-[32rem] divide-y divide-slate-100 overflow-y-auto">
              {experiments.map((e) => (
                <li
                  key={e.id}
                  className={cx(
                    "flex items-center justify-between gap-2 px-5 py-3 text-sm",
                    comparison?.experiment.id === e.id && "bg-brand-50/60"
                  )}
                >
                  <button className="min-w-0 text-left" onClick={() => open(e.id)}>
                    <span className="block truncate font-medium text-brand-700 hover:underline">
                      #{e.id} {e.name}
                    </span>
                    <span className="text-xs text-slate-500">{e.variant_count} variants</span>
                  </button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-red-600 hover:text-red-700"
                    onClick={() =>
                      deleteExperiment(e.id)
                        .then(() => {
                          setComparison(null);
                          return listExperiments().then(setExperiments);
                        })
                        .catch(fail)
                    }
                  >
                    Delete
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {comparison && (
        <Card
          title={comparison.experiment.name}
          description="Hover a difference to see its 95% interval. Scores computed on generated questions are optimistic."
          padded={false}
        >
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="border-b border-slate-200 bg-slate-50">
                <tr>
                  <th className={TH}>Variant</th>
                  {COLUMNS.map((c) => (
                    <th key={c.key} className={TH}>
                      {c.label}
                    </th>
                  ))}
                  <th className={TH}>Retrieval ms</th>
                  <th className={TH}>LLM calls</th>
                  <th className={TH}>MRR</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 align-top tabular-nums">
                {comparison.variants.map((row) => (
                  <tr key={row.index}>
                    <td className={cx(TD, "font-medium text-slate-900")}>
                      {row.label}
                      {row.index === 0 && <span className="ml-1 font-normal text-slate-400">(baseline)</span>}
                    </td>
                    {COLUMNS.map((c) => {
                      const v = value(row, c.key);
                      return (
                        <td key={c.key} className={TD}>
                          {v === undefined ? (row.run_id === null ? "…" : "—") : v.toFixed(3)}
                          <DeltaText delta={row.delta_vs_baseline?.[c.key]} />
                        </td>
                      );
                    })}
                    <td className={TD}>{row.metrics?.retrieval_ms !== undefined ? Math.round(row.metrics.retrieval_ms) : "—"}</td>
                    <td className={TD}>{row.run_id === null ? "—" : row.llm_calls}</td>
                    <td className={cx(TD, "w-32")}>
                      <div className="mt-1 h-2.5 w-full rounded-full bg-slate-100">
                        <div
                          className="h-2.5 rounded-full bg-brand-500"
                          style={{ width: `${((value(row, "mrr") ?? 0) / maxMrr) * 100}%` }}
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
