"use client";

import { useEffect, useState } from "react";
import { retrieveDebug, RetrievalResult } from "@/lib/retrieval";
import { askQuestion, QueryResponse } from "@/lib/query";
import { listDocuments, DocumentSummary } from "@/lib/documents";

export default function RetrievalLabPage() {
  const [question, setQuestion] = useState("");
  const [k, setK] = useState(5);
  const [threshold, setThreshold] = useState(0.8);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [results, setResults] = useState<RetrievalResult[] | null>(null);
  const [answer, setAnswer] = useState<QueryResponse | null>(null);
  const [runFullAnswer, setRunFullAnswer] = useState(false);

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

    try {
      const debugResult = await retrieveDebug(question, k, threshold, selectedIds);
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

  // Recompute above/below threshold client-side as the slider moves,
  // without re-querying — distances are already in hand.
  const displayResults = results?.map((r) => ({
    ...r,
    above_threshold: r.distance <= threshold,
  }));

  return (
    <main className="min-h-screen p-8 flex flex-col items-center">
      <h1 className="text-2xl font-bold mb-2">Retrieval Laboratory</h1>
      <p className="text-sm text-gray-500 mb-6 text-center max-w-lg">
        See exactly what retrieval finds for a query — every candidate chunk,
        its similarity distance, and whether it would pass your threshold.
        No LLM call unless you ask for one.
      </p>

      <div className="w-full max-w-3xl space-y-4">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Type a question to debug retrieval for..."
          className="w-full border border-gray-300 rounded-lg p-3 text-sm"
          rows={2}
        />

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
            Similarity threshold (cosine distance): <span className="font-semibold">{threshold.toFixed(2)}</span>
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
          {loading ? "Retrieving..." : "Run Retrieval"}
        </button>

        {error && <div className="text-red-600 text-sm">{error}</div>}

        {answer && (
          <div className="border border-blue-300 rounded-lg p-3 bg-blue-50 text-sm">
            <p className="font-semibold mb-1">Full answer (from /query):</p>
            <p>{answer.answer}</p>
          </div>
        )}

        {displayResults && (
          <div className="space-y-2">
            <p className="text-sm font-medium">{displayResults.length} candidate(s) retrieved</p>
            {displayResults.map((r, i) => (
              <div
                key={r.chunk_id}
                className={`border rounded-lg p-3 text-sm ${
                  r.above_threshold
                    ? "border-green-300 bg-green-50"
                    : "border-gray-300 bg-gray-50 opacity-60"
                }`}
              >
                <div className="flex justify-between text-xs text-gray-500 mb-1">
                  <span>
                    #{i + 1} — {r.filename}
                    {r.page_number !== null ? ` (page ${r.page_number})` : ""}
                  </span>
                  <span>
                    distance: <strong>{r.distance.toFixed(3)}</strong>{" "}
                    {r.above_threshold ? "✓ included" : "✗ excluded"}
                  </span>
                </div>
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