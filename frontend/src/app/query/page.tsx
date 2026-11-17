"use client";

import Markdown from "@/components/Markdown";
import Link from "next/link";
import { useEffect, useState } from "react";
import { askQuestion, QueryResponse } from "@/lib/query";
import { listDocuments, DocumentSummary } from "@/lib/documents";
import { useWorkspace } from "@/lib/workspace-context";
import { Alert, Badge, Button, Card, Field, PageHeader, inputClass } from "@/components/ui";
import { ChevronIcon, DocumentsIcon } from "@/components/icons";

export default function QueryPage() {
  const { workspaceId } = useWorkspace();
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);

  useEffect(() => {
    setSelectedIds([]);
    setResult(null);
    setError("");
    listDocuments("processed").then(setDocuments).catch(() => {});
  }, [workspaceId]);

  const toggleDocument = (id: number) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const handleAsk = async () => {
    if (!question.trim()) return;
    setLoading(true);
    setResult(null);
    setError("");
    try {
      const data = await askQuestion(question, selectedIds);
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Query failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Quick answer"
        description="Ask a one-off question and get an answer grounded in your processed documents, with the sources it used. Optionally scope it to specific documents."
      />

      <Card>
        <div className="space-y-4">
          <Field label="Question">
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="What would you like to know?"
              className={inputClass}
              rows={3}
            />
          </Field>

          {documents.length > 0 && (
            <details className="group rounded-lg border border-slate-200 bg-slate-50/60">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-3 py-2.5 text-sm font-medium text-slate-700">
                <span>
                  Scope to specific documents{" "}
                  <span className="font-normal text-slate-500">(optional)</span>
                </span>
                <span className="flex items-center gap-2">
                  <Badge tone={selectedIds.length > 0 ? "brand" : "neutral"}>{selectedIds.length} selected</Badge>
                  <ChevronIcon className="h-4 w-4 text-slate-400 transition-transform group-open:rotate-180" />
                </span>
              </summary>
              <div className="scrollbar-thin max-h-48 space-y-0.5 overflow-y-auto border-t border-slate-200 p-2">
                {documents.map((d) => (
                  <label
                    key={d.id}
                    className="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-slate-700 hover:bg-white"
                  >
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(d.id)}
                      onChange={() => toggleDocument(d.id)}
                      className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                    />
                    <span className="font-mono text-xs text-slate-400">#{d.id}</span>
                    <span className="truncate">{d.filename}</span>
                  </label>
                ))}
              </div>
            </details>
          )}

          {documents.length === 0 && (
            <p className="text-xs text-slate-500">
              No processed documents in this workspace yet.{" "}
              <Link href="/upload" className="font-medium text-brand-600 hover:text-brand-700">
                Upload some
              </Link>{" "}
              to get grounded answers.
            </p>
          )}

          <div className="flex items-center justify-end">
            <Button onClick={handleAsk} disabled={!question.trim()} loading={loading}>
              {loading ? "Thinking…" : "Ask"}
            </Button>
          </div>
        </div>
      </Card>

      {error && <Alert tone="error">{error}</Alert>}

      {result && (
        <Card title="Answer">
          <Markdown text={result.answer} className="text-sm leading-6 text-slate-900" />
        </Card>
      )}

      {result && result.sources.length > 0 && (
        <Card title="Sources" description="The documents the answer was grounded in." padded={false}>
          <ul className="divide-y divide-slate-100">
              {result.sources.map((s) => (
                <li
                  key={`${s.document_id}-${s.page_number ?? "na"}`}
                  className="flex items-center justify-between gap-3 px-5 py-3 text-sm"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <DocumentsIcon className="h-4 w-4 shrink-0 text-slate-400" />
                    <span className="truncate font-medium text-slate-900">{s.filename}</span>
                    {s.page_number !== null && <Badge>page {s.page_number}</Badge>}
                  </span>
                  <span className="shrink-0 font-mono text-xs text-slate-500" title="Relevance score">
                    relevance {s.score.toFixed(3)}
                  </span>
                </li>
              ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
