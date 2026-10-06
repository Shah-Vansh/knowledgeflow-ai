"use client";

import { useEffect, useState } from "react";
import {
  listDocuments,
  rechunkDocument,
  getDocumentChunks,
  DocumentSummary,
  ChunkInfo,
} from "@/lib/documents";
import { askQuestion } from "@/lib/query";

interface ConfigState {
  strategy: string;
  chunk_size: number;
  overlap: number;
}

function ConfigPanel({
  label,
  config,
  setConfig,
}: {
  label: string;
  config: ConfigState;
  setConfig: (c: ConfigState) => void;
}) {
  return (
    <div className="border border-gray-300 rounded-lg p-3 bg-white space-y-2">
      <p className="font-semibold text-sm">{label}</p>
      <label className="block text-sm">
        Strategy
        <select
          value={config.strategy}
          onChange={(e) => setConfig({ ...config, strategy: e.target.value })}
          className="block w-full border border-gray-300 rounded p-1 mt-1"
        >
          <option value="fixed_size">fixed_size</option>
          <option value="recursive">recursive</option>
          <option value="sentence">sentence</option>
        </select>
      </label>
      <label className="block text-sm">
        Chunk size
        <input
          type="number"
          value={config.chunk_size}
          onChange={(e) => setConfig({ ...config, chunk_size: Number(e.target.value) })}
          className="block w-full border border-gray-300 rounded p-1 mt-1"
        />
      </label>
      <label className="block text-sm">
        Overlap
        <input
          type="number"
          value={config.overlap}
          onChange={(e) => setConfig({ ...config, overlap: Number(e.target.value) })}
          className="block w-full border border-gray-300 rounded p-1 mt-1"
        />
      </label>
    </div>
  );
}

function ResultPanel({ chunks, answer }: { chunks: ChunkInfo[] | null; answer: string | null }) {
  if (!chunks) return null;
  return (
    <div className="border border-gray-300 rounded-lg p-3 bg-white space-y-2 text-sm">
      <p className="font-medium">{chunks.length} chunk(s)</p>
      {answer && (
        <div className="bg-gray-50 border border-gray-200 rounded p-2">
          <p className="font-semibold">Test answer:</p>
          <p>{answer}</p>
        </div>
      )}
      <div className="max-h-64 overflow-y-auto space-y-2">
        {chunks.slice(0, 5).map((c) => (
          <div key={c.id} className="border border-gray-200 rounded p-2">
            <p className="text-xs text-gray-500">chunk #{c.chunk_index}</p>
            <p>{c.content}</p>
          </div>
        ))}
        {chunks.length > 5 && <p className="text-xs text-gray-500">...and {chunks.length - 5} more</p>}
      </div>
    </div>
  );
}

export default function ChunkingLabPage() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [documentId, setDocumentId] = useState<number | null>(null);
  const [testQuestion, setTestQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [configA, setConfigA] = useState<ConfigState>({ strategy: "fixed_size", chunk_size: 200, overlap: 0 });
  const [configB, setConfigB] = useState<ConfigState>({ strategy: "recursive", chunk_size: 500, overlap: 0 });

  const [chunksA, setChunksA] = useState<ChunkInfo[] | null>(null);
  const [chunksB, setChunksB] = useState<ChunkInfo[] | null>(null);
  const [answerA, setAnswerA] = useState<string | null>(null);
  const [answerB, setAnswerB] = useState<string | null>(null);

  useEffect(() => {
    listDocuments()
      .then((docs) => {
        setDocuments(docs);
        if (docs.length > 0) setDocumentId(docs[0].id);
      })
      .catch(() => setError("Could not load documents"));
  }, []);

  const runComparison = async () => {
    if (!documentId) return;
    setLoading(true);
    setError("");
    setChunksA(null);
    setChunksB(null);
    setAnswerA(null);
    setAnswerB(null);

    try {
      await rechunkDocument(documentId, configA);
      const resultA = await getDocumentChunks(documentId);
      setChunksA(resultA);
      if (testQuestion.trim()) {
        const qa = await askQuestion(testQuestion);
        setAnswerA(qa.answer);
      }

      await rechunkDocument(documentId, configB);
      const resultB = await getDocumentChunks(documentId);
      setChunksB(resultB);
      if (testQuestion.trim()) {
        const qb = await askQuestion(testQuestion);
        setAnswerB(qb.answer);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Comparison failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen p-8 flex flex-col items-center">
      <h1 className="text-2xl font-bold mb-2">Chunking Laboratory</h1>
      <p className="text-sm text-gray-500 mb-6 text-center max-w-lg">
        Pick a document, configure two chunking setups, and compare the resulting chunks
        (and optionally a test question) side by side. Running the comparison rechunks the
        document in place — first under Config A, then Config B.
      </p>

      <div className="w-full max-w-4xl space-y-4">
        <div className="border border-gray-300 rounded-lg p-3 bg-white space-y-3">
          <label className="block text-sm">
            Document
            <select
              value={documentId ?? ""}
              onChange={(e) => setDocumentId(Number(e.target.value))}
              className="block w-full border border-gray-300 rounded p-1 mt-1"
            >
              {documents.map((d) => (
                <option key={d.id} value={d.id}>
                  #{d.id} — {d.filename} ({d.status})
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            Test question (optional — runs against /query after each config)
            <input
              type="text"
              value={testQuestion}
              onChange={(e) => setTestQuestion(e.target.value)}
              placeholder="e.g. What is the return policy?"
              className="block w-full border border-gray-300 rounded p-1 mt-1"
            />
          </label>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ConfigPanel label="Config A" config={configA} setConfig={setConfigA} />
          <ConfigPanel label="Config B" config={configB} setConfig={setConfigB} />
        </div>

        <button
          onClick={runComparison}
          disabled={!documentId || loading}
          className="w-full bg-blue-600 text-white rounded-lg py-2 disabled:opacity-50"
        >
          {loading ? "Running comparison..." : "Run Comparison"}
        </button>

        {error && <div className="text-red-600 text-sm">{error}</div>}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ResultPanel chunks={chunksA} answer={answerA} />
          <ResultPanel chunks={chunksB} answer={answerB} />
        </div>

        <a href="/upload" className="block text-center text-blue-600 underline text-sm">
          ← Back to Upload
        </a>
      </div>
    </main>
  );
}