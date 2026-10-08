"use client";

import { useEffect, useState } from "react";
import { askQuestion, QueryResponse } from "@/lib/query";
import { listDocuments, DocumentSummary } from "@/lib/documents";

export default function QueryPage() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [loading, setLoading] = useState(false);

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

  const handleAsk = async () => {
    if (!question.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const data = await askQuestion(question, selectedIds);
      setResult(data);
    } catch (err) {
      setResult({ answer: err instanceof Error ? err.message : "Query failed", sources: [] });
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen flex flex-col items-center justify-center p-8">
      <h1 className="text-2xl font-bold mb-6">Ask a Question</h1>
      <div className="w-full max-w-lg space-y-4">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="What would you like to know?"
          className="w-full border border-gray-300 rounded-lg p-3 text-sm"
          rows={3}
        />

        {documents.length > 0 && (
          <details className="text-sm border border-gray-300 rounded-lg p-3 bg-white">
            <summary className="cursor-pointer font-medium">
              Scope to specific documents (optional — {selectedIds.length} selected)
            </summary>
            <div className="mt-3 space-y-1 max-h-40 overflow-y-auto">
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

        <button
          onClick={handleAsk}
          disabled={!question.trim() || loading}
          className="w-full bg-blue-600 text-white rounded-lg py-2 disabled:opacity-50"
        >
          {loading ? "Thinking..." : "Ask"}
        </button>

        {result && (
          <div className="rounded-lg border border-gray-300 p-4 bg-white space-y-3">
            <p className="font-semibold">{result.answer}</p>
            {result.sources.length > 0 && (
              <div className="text-xs text-gray-500">
                <p className="font-medium mb-1">Sources:</p>
                <ul className="list-disc list-inside space-y-1">
                  {result.sources.map((s) => (
                    <li key={`${s.document_id}-${s.page_number ?? "na"}`}>
                      {s.filename}
                      {s.page_number !== null ? ` — page ${s.page_number}` : ""}
                      {" "}(relevance score: {s.score.toFixed(3)})
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        <div className="flex justify-between text-sm">
          <a href="/upload" className="text-blue-600 underline">← Go to Upload page</a>
          <a href="/documents" className="text-blue-600 underline">Manage Documents →</a>
        </div>
      </div>
    </main>
  );
}