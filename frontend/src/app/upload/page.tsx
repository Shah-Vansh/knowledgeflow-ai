"use client";

import { useEffect, useState } from "react";
import { uploadDocument } from "@/lib/documents";
import { listWorkspaces, Workspace } from "@/lib/workspaces";

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<string>("");
  const [loading, setLoading] = useState(false);

  const [strategy, setStrategy] = useState("fixed_size");
  const [chunkSize, setChunkSize] = useState(500);
  const [overlap, setOverlap] = useState(0);

  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<number>(1);

  useEffect(() => {
    listWorkspaces()
      .then((list) => {
        setWorkspaces(list);
        if (list.length > 0 && !list.some((w) => w.id === 1)) setWorkspaceId(list[0].id);
      })
      .catch(() => {});
  }, []);

  const handleUpload = async () => {
    if (!file) return;
    setLoading(true);
    setStatus("");
    try {
      const result = await uploadDocument(
        file,
        { strategy, chunk_size: chunkSize, overlap },
        workspaceId
      );
      const where = workspaces.find((w) => w.id === result.workspace_id)?.name ?? `#${result.workspace_id}`;
      setStatus(
        `Uploaded "${result.filename}" to workspace "${where}" — status: ${result.status} (document_id: ${result.document_id})`
      );
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
        <label className="block text-sm">
          Workspace
          <select
            value={workspaceId}
            onChange={(e) => setWorkspaceId(Number(e.target.value))}
            className="block w-full border border-gray-300 rounded p-2 mt-1 bg-white"
          >
            {workspaces.length === 0 && <option value={1}>General</option>}
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </label>

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
          <div className="rounded-lg border border-gray-300 p-3 text-sm bg-white">{status}</div>
        )}
        <div className="flex flex-wrap justify-between gap-2 text-sm">
          <a href="/chat" className="text-blue-600 underline">
            Chat →
          </a>
          <a href="/workspaces" className="text-blue-600 underline">
            Workspaces →
          </a>
          <a href="/query" className="text-blue-600 underline">
            Query →
          </a>
          <a href="/chunking-lab" className="text-blue-600 underline">
            Chunking Lab →
          </a>
        </div>
      </div>
    </main>
  );
}