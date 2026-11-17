"use client";

import { useEffect, useMemo, useState } from "react";
import { ChunkInfo, DocumentSummary, getDocumentChunks, listDocuments } from "@/lib/documents";
import { useWorkspace } from "@/lib/workspace-context";
import {
  Alert,
  Badge,
  BadgeTone,
  ButtonLink,
  Card,
  EmptyState,
  Field,
  Loading,
  PageHeader,
  Segmented,
  Stat,
  StatusBadge,
  inputClass,
} from "@/components/ui";
import { InspectIcon } from "@/components/icons";

const TYPE_LABEL: Record<string, string> = {
  text: "Text",
  table: "Table",
  ocr: "OCR page",
  image_text: "Image text",
};

const TYPE_TONE: Record<string, BadgeTone> = {
  text: "neutral",
  table: "brand",
  ocr: "warning",
  image_text: "success",
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
        <div className="overflow-x-auto rounded-lg bg-slate-50 p-3">
          <table className="min-w-full border border-slate-200 bg-white text-xs">
            <thead>
              <tr>
                {header.map((cell, i) => (
                  <th
                    key={i}
                    className="border border-slate-200 bg-slate-50 px-2 py-1 text-left font-medium text-slate-700"
                  >
                    {cell}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {body.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, c) => (
                    <td key={c} className="border border-slate-200 px-2 py-1 text-slate-700">
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
  return (
    <p className="max-h-40 overflow-y-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm leading-6 text-slate-700">
      {chunk.content}
    </p>
  );
}

export default function InspectorPage() {
  const { workspaceId, workspace } = useWorkspace();
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [documentId, setDocumentId] = useState<number | null>(null);
  const [chunks, setChunks] = useState<ChunkInfo[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [error, setError] = useState("");
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [loadingChunks, setLoadingChunks] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setDocuments([]);
    setDocumentId(null);
    setChunks([]);
    setError("");
    setLoadingDocs(true);
    listDocuments(undefined, workspaceId)
      .then((list) => {
        if (cancelled) return;
        setDocuments(list);
        if (list.length > 0) setDocumentId(list[list.length - 1].id);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load documents");
      })
      .finally(() => {
        if (!cancelled) setLoadingDocs(false);
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  useEffect(() => {
    if (documentId === null) return;
    let cancelled = false;
    setFilter("all");
    setChunks([]);
    setLoadingChunks(true);
    getDocumentChunks(documentId)
      .then((list) => {
        if (!cancelled) setChunks(list);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load chunks");
      })
      .finally(() => {
        if (!cancelled) setLoadingChunks(false);
      });
    return () => {
      cancelled = true;
    };
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

  const filterOptions = [
    { value: "all", label: `All (${chunks.length})` },
    ...Object.keys(counts).map((type) => ({
      value: type,
      label: `${TYPE_LABEL[type] ?? type} (${counts[type]})`,
    })),
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Document inspector"
        description="See how a file was processed: digital text, tables, pages read with OCR, and text found inside images. Image content with no readable text is not searchable."
      />

      {error && <Alert tone="error">{error}</Alert>}

      {loadingDocs ? (
        <Loading label="Loading documents…" />
      ) : documents.length === 0 ? (
        <EmptyState
          icon={<InspectIcon className="h-8 w-8" />}
          title="No documents to inspect"
          description={`Upload a file to ${workspace?.name ?? "this workspace"} to see how it was processed.`}
          action={
            <ButtonLink href="/upload" variant="primary">
              Upload a document
            </ButtonLink>
          }
        />
      ) : (
        <>
          <Card>
            <Field label="Document" hint={`Documents in ${workspace?.name ?? "the active workspace"}`}>
              <select
                value={documentId ?? ""}
                onChange={(e) => setDocumentId(Number(e.target.value))}
                className={inputClass}
              >
                {documents.map((d) => (
                  <option key={d.id} value={d.id}>
                    #{d.id} — {d.filename}
                    {d.status !== "processed" ? ` (${d.status})` : ""}
                  </option>
                ))}
              </select>
            </Field>
          </Card>

          {document && (
            <Card
              title={<span className="break-all">{document.filename}</span>}
              description={
                <>
                  {document.source_type ?? "?"}
                  {document.page_count !== null ? ` · ${document.page_count} page(s)` : ""}
                </>
              }
              actions={<StatusBadge status={document.status} />}
            >
              {report ? (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
                    <Stat label="Digital text pages" value={report.pages_text} />
                    <Stat label="OCR pages" value={report.pages_ocr} />
                    <Stat label="Tables" value={report.tables} />
                    <Stat label="Images with text" value={report.images_ocr} />
                    {report.images_skipped > 0 && (
                      <Stat label="Images skipped" value={report.images_skipped} hint="Too small or no text" />
                    )}
                    <Stat label="OCR engine" value={report.ocr_available ? "Yes" : "No"} hint="Available" />
                  </div>
                  {report.notes.length > 0 && (
                    <Alert tone="warning">
                      <ul className="space-y-0.5">
                        {report.notes.map((note, i) => (
                          <li key={i}>{note}</li>
                        ))}
                      </ul>
                    </Alert>
                  )}
                </div>
              ) : (
                <p className="text-sm text-slate-500">
                  No processing report (this file was uploaded before multimodal support).
                </p>
              )}
            </Card>
          )}

          {loadingChunks ? (
            <Loading label="Loading chunks…" />
          ) : (
            chunks.length > 0 && (
              <section className="space-y-3">
                <div className="overflow-x-auto">
                  <Segmented options={filterOptions} value={filter} onChange={setFilter} />
                </div>

                <div className="space-y-3">
                  {visible.map((chunk) => (
                    <div key={chunk.id} className="space-y-2 rounded-xl border border-slate-200 bg-white p-4 shadow-card">
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <Badge tone={TYPE_TONE[chunk.chunk_type] ?? "neutral"}>
                          {TYPE_LABEL[chunk.chunk_type] ?? chunk.chunk_type}
                        </Badge>
                        <span className="text-slate-500">
                          chunk {chunk.chunk_index}
                          {chunk.page_number !== null ? ` · page ${chunk.page_number}` : ""}
                        </span>
                        {chunk.ocr_confidence !== null && (
                          <span
                            className={
                              chunk.ocr_confidence < 0.8 ? "font-medium text-red-600" : "text-slate-500"
                            }
                          >
                            OCR confidence {Math.round(chunk.ocr_confidence * 100)}%
                          </span>
                        )}
                      </div>
                      <ChunkBody chunk={chunk} />
                    </div>
                  ))}
                </div>
              </section>
            )
          )}
        </>
      )}
    </div>
  );
}
