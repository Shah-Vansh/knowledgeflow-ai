"use client";

import { useState } from "react";
import { askQuestion, QueryResponse } from "@/lib/query";

export default function QueryPage() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const handleAsk = async () => {
    if (!question.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const data = await askQuestion(question);
      setResult(data);
    } catch (err) {
      setResult({ answer: err instanceof Error ? err.message : "Query failed", chunks_used: [] });
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
            {result.chunks_used.length > 0 && (
              <div className="text-xs text-gray-500">
                <p className="font-medium mb-1">Chunks used:</p>
                <ul className="list-disc list-inside space-y-1">
                  {result.chunks_used.map((c) => (
                    <li key={c.chunk_id}>
                      doc #{c.document_id}, chunk #{c.chunk_index} (distance: {c.distance.toFixed(3)})
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        <a href="/upload" className="block text-center text-blue-600 underline text-sm">
          ← Go to Upload page
        </a>
      </div>
    </main>
  );
}