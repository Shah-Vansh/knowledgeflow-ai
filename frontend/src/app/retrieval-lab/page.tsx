"use client";

import { useEffect, useState } from "react";
import { retrieveDebug, RetrievalResult, RetrievalMode } from "@/lib/retrieval";
import { askQuestion, QueryResponse } from "@/lib/query";
import { listDocuments, DocumentSummary } from "@/lib/documents";

function RankChange({ before, after }: { before: number; after: number }) {
  const arrow = before > after ? "▲" : before < after ? "▼" : "=";
  const color =
    before > after ? "text-green-700" : before < after ? "text-red-600" : "text-gray-500";
  return (
    <span className={`font-medium ${color}`}>
      {arrow} was #{before} → now #{after}
    </span>
  );
}

export default function RetrievalLabPage() {
  const [question, setQuestion] = useState("");
  const [k, setK] = useState(5);
  const [threshold, setThreshold] = useState(0.8);
  const [mode, setMode] = useState<RetrievalMode>("hybrid");
  const [rerank, setRerank] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [results, setResults] = useState<RetrievalResult[] | null>(null);
  const [answer, setAnswer] = useState<QueryResponse | null>(null);
  const [runFullAnswer, setRunFullAnswer] = useState(false);
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);

  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);

  useEffect(() => {
    listDocuments("processed").then(setDocuments).catch(() => {});
  }, []);

  const toggleDocument = (id: number) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const runRetrieval = async () => {
    if (!question.trim()) return;
    setLoading(true);
    setError("");
    setResults(null);
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
        mode === "hybrid" && rerank
      );
      setElapsedMs(performance.now() - started);
      setResults(debugResult.results);

      if (runFullAnswer) {
        const qa = await askQuestion(question, selectedIds);
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

  return (
    <main className="min-h-screen p-8 flex flex-col items-center">
      <h1 className="text-2xl font-bold mb-2">Retrieval Laboratory</h1>
      <p className="text-sm text-gray-500 mb-6 text-center max-w-lg">
        Compare Dense, Sparse (PostgreSQL full-text), and Hybrid (RRF-fused) retrieval
        on the same query — and see what a cross-encoder reranker changes.
      </p>

      <div className="w-full max-w-3xl space-y-4">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Type a question to debug retrieval for..."
          className="w-full border border-gray-300 rounded-lg p-3 text-sm"
          rows={2}
        />

        <div className="flex flex-wrap items-center gap-4">
          <div className="flex gap-2 border border-gray-300 rounded-lg p-1 bg-white w-fit">
            {(["dense", "sparse", "hybrid"] as RetrievalMode[]).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`px-4 py-1.5 rounded text-sm capitalize ${
                  mode === m ? "bg-blue-600 text-white" : "text-gray-600"
                }`}
              >
                {m}
              </button>
            ))}
          </div>

          <label
            className={`flex items-center gap-2 text-sm ${
              mode === "hybrid" ? "" : "opacity-40"
            }`}
          >
            <input
              type="checkbox"
              checked={rerank}
              disabled={mode !== "hybrid"}
              onChange={(e) => setRerank(e.target.checked)}
            />
            Rerank with cross-encoder (hybrid only)
          </label>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="block text-sm border border-gray-300 rounded-lg p-3 bg-white">
            Top-k: <span className="font-semibold">{k}</span>
            <input
              type="range"
              min={1}
              max={20}
              value={k}
              onChange={(e) => setK(Number(e.target.value))}
              className="block w-full mt-1"
            />
          </label>
          <label className="block text-sm border border-gray-300 rounded-lg p-3 bg-white">
            Similarity threshold (dense mode only): <span className="font-semibold">{threshold.toFixed(2)}</span>
            <input
              type="range"
              min={0}
              max={1.5}
              step={0.01}
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
              className="block w-full mt-1"
            />
            <span className="text-xs text-gray-500">Lower = stricter (more similar required)</span>
          </label>
        </div>

        {documents.length > 0 && (
          <details className="text-sm border border-gray-300 rounded-lg p-3 bg-white">
            <summary className="cursor-pointer font-medium">
              Scope to specific documents (optional — {selectedIds.length} selected)
            </summary>
            <div className="mt-3 space-y-1 max-h-32 overflow-y-auto">
              {documents.map((d) => (
                <label key={d.id} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(d.id)}
                    onChange={() => toggleDocument(d.id)}
                  />
                  <span>#{d.id} — {d.filename}</span>
                </label>
              ))}
            </div>
          </details>
        )}

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={runFullAnswer}
            onChange={(e) => setRunFullAnswer(e.target.checked)}
          />
          Also run full answer (calls the LLM) for comparison
        </label>

        <button
          onClick={runRetrieval}
          disabled={!question.trim() || loading}
          className="w-full bg-blue-600 text-white rounded-lg py-2 disabled:opacity-50"
        >
          {loading
            ? "Retrieving..."
            : `Run ${mode[0].toUpperCase()}${mode.slice(1)} Retrieval${
                mode === "hybrid" && rerank ? " + Rerank" : ""
              }`}
        </button>

        {error && <div className="text-red-600 text-sm">{error}</div>}

        {answer && (
          <div className="border border-blue-300 rounded-lg p-3 bg-blue-50 text-sm">
            <p className="font-semibold mb-1">
              Full answer (from /query — hybrid, reranked if enabled on the server):
            </p>
            <p>{answer.answer}</p>
          </div>
        )}

        {displayResults && (
          <div className="space-y-2">
            <p className="text-sm font-medium">
              {displayResults.length} candidate(s) retrieved
              {elapsedMs !== null && (
                <span className="text-gray-500 font-normal"> · {Math.round(elapsedMs)} ms</span>
              )}
            </p>
            {displayResults.map((r, i) => (
              <div
                key={r.chunk_id}
                className={`border rounded-lg p-3 text-sm ${
                  r.above_threshold
                    ? "border-green-300 bg-green-50"
                    : "border-gray-300 bg-gray-50 opacity-60"
                }`}
              >
                <div className="flex justify-between gap-4 text-xs text-gray-500 mb-1">
                  <span>
                    #{i + 1} — {r.filename}
                    {r.page_number !== null ? ` (page ${r.page_number})` : ""}
                    {r.found_by.length > 0 ? ` · found by: ${r.found_by.join(" + ")}` : ""}
                  </span>
                  <span className="text-right">
                    {r.dense_distance !== null && <>dist: <strong>{r.dense_distance.toFixed(3)}</strong> </>}
                    {r.sparse_score !== null && <>fts: <strong>{r.sparse_score.toFixed(3)}</strong> </>}
                    {r.rrf_score !== null && <>rrf: <strong>{r.rrf_score.toFixed(4)}</strong> </>}
                    {r.rerank_score !== null && <>rerank: <strong>{r.rerank_score.toFixed(3)}</strong> </>}
                    {mode === "dense" ? (r.above_threshold ? "✓ included" : "✗ excluded") : ""}
                  </span>
                </div>
                {r.pre_rerank_rank !== null && r.post_rerank_rank !== null && (
                  <div className="text-xs mb-1">
                    <RankChange before={r.pre_rerank_rank} after={r.post_rerank_rank} />
                  </div>
                )}
                <p>{r.content}</p>
              </div>
            ))}
          </div>
        )}

        <div className="flex justify-between text-sm pt-2">
          <a href="/query" className="text-blue-600 underline">← Query page</a>
          <a href="/chunking-lab" className="text-blue-600 underline">Chunking Lab →</a>
        </div>
      </div>
    </main>
  );
}