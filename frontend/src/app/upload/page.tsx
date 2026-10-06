"use client";

import { useState } from "react";
import { uploadDocument } from "@/lib/documents";

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<string>("");
  const [loading, setLoading] = useState(false);

  const [strategy, setStrategy] = useState("fixed_size");
  const [chunkSize, setChunkSize] = useState(500);
  const [overlap, setOverlap] = useState(0);

  const handleUpload = async () => {
    if (!file) return;
    setLoading(true);
    setStatus("");
    try {
      const result = await uploadDocument(file, { strategy, chunk_size: chunkSize, overlap });
      setStatus(`Uploaded "${result.filename}" — status: ${result.status} (document_id: ${result.document_id})`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen flex flex-col items-center justify-center p-8">
      <h1 className="text-2xl font-bold mb-6">Upload a Document</h1>
      <div className="w-full max-w-md space-y-4">
        <input
          type="file"
          accept=".pdf,.txt"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="block w-full text-sm border border-gray-300 rounded-lg p-2"
        />

        <details className="text-sm border border-gray-300 rounded-lg p-3 bg-white">
          <summary className="cursor-pointer font-medium">Chunking options (optional)</summary>
          <div className="mt-3 space-y-2">
            <label className="block">
              Strategy
              <select
                value={strategy}
                onChange={(e) => setStrategy(e.target.value)}
                className="block w-full border border-gray-300 rounded p-1 mt-1"
              >
                <option value="fixed_size">fixed_size</option>
                <option value="recursive">recursive</option>
                <option value="sentence">sentence</option>
              </select>
            </label>
            <label className="block">
              Chunk size
              <input
                type="number"
                value={chunkSize}
                onChange={(e) => setChunkSize(Number(e.target.value))}
                className="block w-full border border-gray-300 rounded p-1 mt-1"
              />
            </label>
            <label className="block">
              Overlap
              <input
                type="number"
                value={overlap}
                onChange={(e) => setOverlap(Number(e.target.value))}
                className="block w-full border border-gray-300 rounded p-1 mt-1"
              />
            </label>
          </div>
        </details>

        <button
          onClick={handleUpload}
          disabled={!file || loading}
          className="w-full bg-blue-600 text-white rounded-lg py-2 disabled:opacity-50"
        >
          {loading ? "Uploading..." : "Upload"}
        </button>
        {status && (
          <div className="rounded-lg border border-gray-300 p-3 text-sm bg-white">
            {status}
          </div>
        )}
        <div className="flex justify-between text-sm">
          <a href="/query" className="text-blue-600 underline">Go to Query page →</a>
          <a href="/chunking-lab" className="text-blue-600 underline">Chunking Lab →</a>
        </div>
      </div>
    </main>
  );
}