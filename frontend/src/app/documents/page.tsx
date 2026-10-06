"use client";

import { useEffect, useState } from "react";
import { listDocuments, deleteDocument, DocumentSummary } from "@/lib/documents";

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [error, setError] = useState("");
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const load = () => {
    listDocuments()
      .then(setDocuments)
      .catch(() => setError("Could not load documents"));
  };

  useEffect(() => {
    load();
  }, []);

  const handleDelete = async (id: number) => {
    setDeletingId(id);
    setError("");
    try {
      await deleteDocument(id);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <main className="min-h-screen p-8 flex flex-col items-center">
      <h1 className="text-2xl font-bold mb-6">Documents</h1>
      <div className="w-full max-w-2xl space-y-3">
        {error && <div className="text-red-600 text-sm">{error}</div>}
        {documents.length === 0 && <p className="text-sm text-gray-500">No documents uploaded yet.</p>}
        {documents.map((d) => (
          <div
            key={d.id}
            className="border border-gray-300 rounded-lg p-3 bg-white flex items-center justify-between"
          >
            <div className="text-sm">
              <p className="font-medium">#{d.id} — {d.filename}</p>
              <p className="text-gray-500">
                {d.status}
                {d.source_type ? ` · ${d.source_type}` : ""}
                {d.page_count !== null ? ` · ${d.page_count} page(s)` : ""}
                {d.uploaded_at ? ` · uploaded ${new Date(d.uploaded_at).toLocaleString()}` : ""}
              </p>
            </div>
            <button
              onClick={() => handleDelete(d.id)}
              disabled={deletingId === d.id}
              className="text-red-600 border border-red-300 rounded px-3 py-1 text-sm disabled:opacity-50"
            >
              {deletingId === d.id ? "Deleting..." : "Delete"}
            </button>
          </div>
        ))}
        <div className="flex justify-between text-sm pt-2">
          <a href="/upload" className="text-blue-600 underline">← Upload</a>
          <a href="/query" className="text-blue-600 underline">Go to Query →</a>
        </div>
      </div>
    </main>
  );
}