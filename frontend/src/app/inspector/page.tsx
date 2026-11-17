"use client";

import { useEffect, useMemo, useState } from "react";
import { listWorkspaces, Workspace } from "@/lib/workspaces";
import { ChunkInfo, DocumentSummary, getDocumentChunks, listDocuments } from "@/lib/documents";

const TYPE_LABEL: Record<string, string> = {
  text: "Text",
  table: "Table",
  ocr: "OCR page",
  image_text: "Image text",
};

const TYPE_STYLE: Record<string, string> = {
  text: "bg-gray-100 text-gray-700",
  table: "bg-indigo-100 text-indigo-800",
  ocr: "bg-amber-100 text-amber-800",
  image_text: "bg-pink-100 text-pink-800",
};

// "| a | b |\n| --- | --- |\n| 1 | 2 |"  ->  [["a","b"],["1","2"]]
function parseMarkdownTable(content: string): string[][] | null {
  const lines = content.split("\n").filter((line) => line.trim().startsWith("|"));
  if (lines.length < 2) return null;
  const rows = lines.map((line) =>
    line
      .trim()
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map((cell) => cell.trim())
  );
  return rows.filter((row) => !row.every((cell) => /^:?-{3,}:?$/.test(cell)));
}

function ChunkBody({ chunk }: { chunk: ChunkInfo }) {
  if (chunk.chunk_type === "table") {
    const rows = parseMarkdownTable(chunk.content);
    if (rows && rows.length > 0) {
      const [header, ...body] = rows;
      return (
        <div className="overflow-x-auto">
          <table className="text-xs border border-gray-300">
            <thead>
              <tr>
                {header.map((cell, i) => (
                  <th key={i} className="border border-gray-300 bg-gray-50 px-2 py-1 text-left">
                    {cell}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {body.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, c) => (
                    <td key={c} className="border border-gray-300 px-2 py-1">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
  }
  return <p className="text-xs whitespace-pre-wrap max-h-40 overflow-y-auto">{chunk.content}</p>;
}

export default function InspectorPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<number | null>(null);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [documentId, setDocumentId] = useState<number | null>(null);
  const [chunks, setChunks] = useState<ChunkInfo[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [error, setError] = useState("");

  useEffect(() => {
    listWorkspaces()
      .then((list) => {
        setWorkspaces(list);
        if (list.length > 0) setWorkspaceId(list[0].id);
      })
      .catch(() => setError("Could not load workspaces"));
  }, []);

  useEffect(() => {
    if (workspaceId === null) return;
    setDocumentId(null);
    setChunks([]);
    setError("");
    listDocuments(undefined, workspaceId)
      .then((list) => {
        setDocuments(list);
        if (list.length > 0) setDocumentId(list[list.length - 1].id);
      })
      .catch(() => setError("Could not load documents"));
  }, [workspaceId]);

  useEffect(() => {
    if (documentId === null) return;
    setFilter("all");
    getDocumentChunks(documentId)
      .then(setChunks)
      .catch(() => setError("Could not load chunks"));
  }, [documentId]);

  const document = documents.find((d) => d.id === documentId) ?? null;
  const report = document?.ingest_report ?? null;

  const counts = useMemo(() => {
    const result: Record<string, number> = {};
    chunks.forEach((c) => {
      result[c.chunk_type] = (result[c.chunk_type] ?? 0) + 1;
    });
    return result;
  }, [chunks]);

  const visible = filter === "all" ? chunks : chunks.filter((c) => c.chunk_type === filter);

  return (
    <main className="min-h-screen p-8 flex flex-col items-center">
      <h1 className="text-2xl font-bold mb-2">Document Inspector</h1>
      <p className="text-sm text-gray-500 mb-6 text-center max-w-xl">
        See how a file was processed: digital text, tables, pages read with OCR, and text found
        inside images. Image content with no readable text is not searchable.
      </p>

      <div className="w-full max-w-4xl space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <label className="block text-sm">
            Workspace
            <select
              value={workspaceId ?? ""}
              onChange={(e) => setWorkspaceId(Number(e.target.value))}
              className="block w-full border border-gray-300 rounded p-2 mt-1 bg-white"
            >
              {workspaces.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            Document
            <select
              value={documentId ?? ""}
              onChange={(e) => setDocumentId(Number(e.target.value))}
              className="block w-full border border-gray-300 rounded p-2 mt-1 bg-white"
            >
              {documents.length === 0 && <option value="">No documents</option>}
              {documents.map((d) => (
                <option key={d.id} value={d.id}>
                  #{d.id} — {d.filename}
                  {d.status !== "processed" ? ` (${d.status})` : ""}
                </option>
              ))}
            </select>
          </label>
        </div>

        {error && <div className="text-red-600 text-sm">{error}</div>}

        {document && (
          <section className="border border-gray-300 rounded-lg bg-white p-4 text-sm space-y-2">
            <p className="font-medium">
              {document.filename}{" "}
              <span className="text-gray-500 font-normal">
                · {document.source_type ?? "?"} · {document.status}
                {document.page_count !== null ? ` · ${document.page_count} page(s)` : ""}
              </span>
            </p>

            {report ? (
              <ul className="text-xs text-gray-700 space-y-0.5">
                <li>Pages with digital text: {report.pages_text}</li>
                <li>Pages read with OCR: {report.pages_ocr}</li>
                <li>Tables found: {report.tables}</li>
                <li>Images with readable text: {report.images_ocr}</li>
                {report.images_skipped > 0 && (
                  <li>Images skipped (too small or no text): {report.images_skipped}</li>
                )}
                <li>OCR engine available: {report.ocr_available ? "yes" : "no"}</li>
              </ul>
            ) : (
              <p className="text-xs text-gray-500">
                No processing report (this file was uploaded before multimodal support).
              </p>
            )}

            {report && report.notes.length > 0 && (
              <ul className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded p-2 space-y-0.5">
                {report.notes.map((note, i) => (
                  <li key={i}>{note}</li>
                ))}
              </ul>
            )}
          </section>
        )}

        {chunks.length > 0 && (
          <section className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => setFilter("all")}
                className={`text-xs rounded-full px-3 py-1 border ${
                  filter === "all" ? "bg-blue-600 text-white border-blue-600" : "bg-white border-gray-300"
                }`}
              >
                All ({chunks.length})
              </button>
              {Object.keys(counts).map((type) => (
                <button
                  key={type}
                  onClick={() => setFilter(type)}
                  className={`text-xs rounded-full px-3 py-1 border ${
                    filter === type ? "bg-blue-600 text-white border-blue-600" : "bg-white border-gray-300"
                  }`}
                >
                  {TYPE_LABEL[type] ?? type} ({counts[type]})
                </button>
              ))}
            </div>

            {visible.map((chunk) => (
              <div key={chunk.id} className="border border-gray-300 rounded-lg bg-white p-3 space-y-2">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className={`px-2 py-0.5 rounded font-medium ${TYPE_STYLE[chunk.chunk_type] ?? "bg-gray-100"}`}>
                    {TYPE_LABEL[chunk.chunk_type] ?? chunk.chunk_type}
                  </span>
                  <span className="text-gray-500">
                    chunk {chunk.chunk_index}
                    {chunk.page_number !== null ? ` · page ${chunk.page_number}` : ""}
                  </span>
                  {chunk.ocr_confidence !== null && (
                    <span
                      className={
                        chunk.ocr_confidence < 0.8 ? "text-red-600 font-medium" : "text-gray-500"
                      }
                    >
                      OCR confidence {Math.round(chunk.ocr_confidence * 100)}%
                    </span>
                  )}
                </div>
                <ChunkBody chunk={chunk} />
              </div>
            ))}
          </section>
        )}

        <div className="flex justify-between text-sm pt-2">
          <a href="/upload" className="text-blue-600 underline">
            ← Upload
          </a>
          <a href="/documents" className="text-blue-600 underline">
            Documents →
          </a>
        </div>
      </div>
    </main>
  );
}