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
import { useWorkspace } from "@/lib/workspace-context";
import {
  Alert,
  Badge,
  Button,
  ButtonLink,
  Card,
  EmptyState,
  Field,
  inputClass,
  Loading,
  PageHeader,
} from "@/components/ui";

interface ConfigState {
  strategy: string;
  chunk_size: number;
  overlap: number;
}

function ConfigFields({ config, setConfig }: { config: ConfigState; setConfig: (c: ConfigState) => void }) {
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <Field label="Strategy">
        <select
          value={config.strategy}
          onChange={(e) => setConfig({ ...config, strategy: e.target.value })}
          className={inputClass}
        >
          <option value="fixed_size">fixed_size</option>
          <option value="recursive">recursive</option>
          <option value="sentence">sentence</option>
        </select>
      </Field>
      <Field label="Chunk size">
        <input
          type="number"
          value={config.chunk_size}
          onChange={(e) => setConfig({ ...config, chunk_size: Number(e.target.value) })}
          className={inputClass}
        />
      </Field>
      <Field label="Overlap">
        <input
          type="number"
          value={config.overlap}
          onChange={(e) => setConfig({ ...config, overlap: Number(e.target.value) })}
          className={inputClass}
        />
      </Field>
    </div>
  );
}

function ResultPanel({ chunks, answer }: { chunks: ChunkInfo[] | null; answer: string | null }) {
  if (!chunks) {
    return <p className="text-sm text-slate-500">Run the comparison to see chunks for this config.</p>;
  }
  return (
    <div className="space-y-3 text-sm">
      <div>
        <Badge tone="brand">{chunks.length} chunk(s)</Badge>
      </div>
      {answer && (
        <div className="rounded-lg border border-brand-200 bg-brand-50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-700">Test answer</p>
          <p className="mt-1 text-slate-800">{answer}</p>
        </div>
      )}
      <div className="max-h-96 space-y-2 overflow-y-auto">
        {chunks.slice(0, 5).map((c) => (
          <div key={c.id} className="rounded-lg bg-slate-50 p-3">
            <div className="mb-1.5 flex items-center gap-2">
              <Badge>#{c.chunk_index}</Badge>
              <Badge tone="neutral">{c.content.length} chars</Badge>
            </div>
            <p className="whitespace-pre-wrap text-sm leading-6 text-slate-700">{c.content}</p>
          </div>
        ))}
        {chunks.length > 5 && <p className="text-xs text-slate-500">...and {chunks.length - 5} more</p>}
      </div>
    </div>
  );
}

export default function ChunkingLabPage() {
  const { workspaceId } = useWorkspace();
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(true);
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
    let cancelled = false;
    setDocuments([]);
    setDocumentId(null);
    setChunksA(null);
    setChunksB(null);
    setAnswerA(null);
    setAnswerB(null);
    setError("");
    setDocumentsLoading(true);
    listDocuments(undefined, workspaceId)
      .then((docs) => {
        if (cancelled) return;
        setDocuments(docs);
        if (docs.length > 0) setDocumentId(docs[0].id);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load documents");
      })
      .finally(() => {
        if (!cancelled) setDocumentsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

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
    <div className="space-y-6">
      <PageHeader
        eyebrow="Lab"
        title="Chunking Laboratory"
        description="Configure two chunking setups and compare the resulting chunks (and optionally a test question) side by side. Running the comparison rechunks the document in place — first under Config A, then Config B."
      />

      {error && <Alert tone="error">{error}</Alert>}

      {documentsLoading ? (
        <Loading label="Loading documents…" />
      ) : documents.length === 0 ? (
        <EmptyState
          title="No documents in this workspace"
          description="Upload a document to experiment with chunking strategies."
          action={<ButtonLink href="/upload" variant="primary">Upload a document</ButtonLink>}
        />
      ) : (
        <>
          <Card title="Setup" description="Pick a document and an optional test question.">
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Document">
                <select
                  value={documentId ?? ""}
                  onChange={(e) => setDocumentId(Number(e.target.value))}
                  className={inputClass}
                >
                  {documents.map((d) => (
                    <option key={d.id} value={d.id}>
                      #{d.id} — {d.filename} ({d.status})
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Test question" hint="Optional — runs against /query after each config.">
                <input
                  type="text"
                  value={testQuestion}
                  onChange={(e) => setTestQuestion(e.target.value)}
                  placeholder="e.g. What is the return policy?"
                  className={inputClass}
                />
              </Field>
            </div>
            <div className="mt-4 flex justify-end">
              <Button onClick={runComparison} disabled={!documentId} loading={loading}>
                {loading ? "Running comparison..." : "Run Comparison"}
              </Button>
            </div>
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card title="Config A">
              <div className="space-y-5">
                <ConfigFields config={configA} setConfig={setConfigA} />
                <div className="border-t border-slate-100 pt-4">
                  <ResultPanel chunks={chunksA} answer={answerA} />
                </div>
              </div>
            </Card>
            <Card title="Config B">
              <div className="space-y-5">
                <ConfigFields config={configB} setConfig={setConfigB} />
                <div className="border-t border-slate-100 pt-4">
                  <ResultPanel chunks={chunksB} answer={answerB} />
                </div>
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
