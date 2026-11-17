"use client";

import { useEffect, useRef, useState } from "react";
import type { DragEvent, KeyboardEvent } from "react";
import { IngestReport, JobStatus, uploadDocument, waitForJob } from "@/lib/documents";
import { useWorkspace } from "@/lib/workspace-context";
import {
  Alert,
  Button,
  ButtonLink,
  Card,
  Field,
  PageHeader,
  Spinner,
  StatusBadge,
  cx,
  inputClass,
} from "@/components/ui";
import { UploadIcon } from "@/components/icons";

const ACCEPT = ".pdf,.txt,.png,.jpg,.jpeg";

type UploadResult = {
  tone: "success" | "error" | "warning";
  title: string;
  details: string[];
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function UploadPage() {
  const { workspaceId, workspace, workspaces, refresh } = useWorkspace();

  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<string>("");
  const [jobState, setJobState] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  const [strategy, setStrategy] = useState("fixed_size");
  const [chunkSize, setChunkSize] = useState(500);
  const [overlap, setOverlap] = useState(0);

  const unmounted = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    unmounted.current = false;
    return () => {
      unmounted.current = true;
    };
  }, []);

  const describe = (
    filename: string,
    wsId: number,
    docStatus: string,
    documentId: number,
    report: IngestReport | null
  ): UploadResult => {
    const where = workspaces.find((w) => w.id === wsId)?.name ?? `#${wsId}`;
    const found = report
      ? [
          report.pages_ocr > 0 ? `${report.pages_ocr} page(s) read with OCR` : "",
          report.tables > 0 ? `${report.tables} table(s)` : "",
          report.images_ocr > 0 ? `${report.images_ocr} image(s) with text` : "",
        ].filter(Boolean)
      : [];
    const details = [`Status: ${docStatus} · document_id: ${documentId}`];
    if (found.length > 0) details.push(`Found: ${found.join(", ")}`);
    if (report && report.notes.length > 0) details.push(`Note: ${report.notes[0]}`);
    return {
      tone: docStatus === "failed" ? "error" : "success",
      title: `Uploaded "${filename}" to workspace "${where}"`,
      details,
    };
  };

  const jobProgress = (job: JobStatus) => {
    if (job.status === "queued") {
      return job.attempts > 0
        ? `Waiting to retry (attempt ${job.attempts} of ${job.max_attempts} failed)...`
        : "Queued — waiting for a worker...";
    }
    if (job.status === "running") return `Processing (attempt ${job.attempts} of ${job.max_attempts})...`;
    return `Job ${job.status}`;
  };

  const handleUpload = async () => {
    if (!file) return;
    setLoading(true);
    setProgress("Uploading...");
    setJobState(null);
    setResult(null);
    try {
      const result = await uploadDocument(
        file,
        { strategy, chunk_size: chunkSize, overlap },
        workspaceId
      );
      if (result.job_id == null) {
        setProgress("");
        setResult(
          describe(result.filename, result.workspace_id, result.status, result.document_id, result.ingest_report)
        );
        refresh();
        return;
      }

      setProgress(`Uploaded "${result.filename}" — queued for processing (job ${result.job_id})`);
      setJobState("queued");
      const job = await waitForJob(
        result.job_id,
        (update) => {
          if (!unmounted.current) {
            setProgress(`"${result.filename}": ${jobProgress(update)}`);
            setJobState(update.status);
          }
        },
        undefined,
        () => unmounted.current
      );
      if (unmounted.current) return;
      setProgress("");
      setJobState(null);
      if (job.status === "succeeded" && job.document) {
        setResult(
          describe(job.document.filename, job.workspace_id, job.document.status, job.document.id, job.document.ingest_report)
        );
        refresh();
      } else if (job.status === "cancelled") {
        setResult({
          tone: "warning",
          title: `"${result.filename}" was not processed`,
          details: [job.last_error ?? "cancelled"],
        });
      } else {
        setResult({
          tone: "error",
          title: `"${result.filename}" failed`,
          details: [job.last_error ?? "processing failed"],
        });
      }
    } catch (err) {
      if (!unmounted.current) {
        setProgress("");
        setJobState(null);
        setResult({ tone: "error", title: "Upload failed", details: [err instanceof Error ? err.message : "Upload failed"] });
      }
    } finally {
      if (!unmounted.current) setLoading(false);
    }
  };

  const chooseFile = (chosen: File | null) => {
    setFile(chosen);
    setResult(null);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    if (loading) return;
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) chooseFile(dropped);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      inputRef.current?.click();
    }
  };

  const workspaceName = workspace?.name ?? `#${workspaceId}`;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Upload a document"
        description="Add a PDF, text file or image to the active workspace. Scanned pages and images are read with OCR, so they can take a minute."
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2" title="File" description={`Uploading to ${workspaceName}`}>
          <div className="space-y-4">
            <div
              role="button"
              tabIndex={0}
              aria-label="Choose a file to upload"
              onClick={() => inputRef.current?.click()}
              onKeyDown={onKeyDown}
              onDragOver={(e) => {
                e.preventDefault();
                if (!loading) setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              className={cx(
                "flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors",
                "focus:outline-none focus:ring-2 focus:ring-brand-500/30",
                dragOver
                  ? "border-brand-500 bg-brand-50"
                  : "border-slate-300 bg-slate-50 hover:border-brand-400 hover:bg-brand-50/40"
              )}
            >
              <input
                ref={inputRef}
                type="file"
                accept={ACCEPT}
                className="sr-only"
                onClick={(e) => e.stopPropagation()}
                onChange={(e) => chooseFile(e.target.files?.[0] ?? null)}
              />
              <UploadIcon className={cx("mb-3 h-8 w-8", dragOver ? "text-brand-600" : "text-slate-400")} />
              {file ? (
                <>
                  <p className="text-sm font-medium text-slate-900 break-all">{file.name}</p>
                  <p className="mt-1 text-xs text-slate-500">
                    {formatSize(file.size)} · click or drop to choose a different file
                  </p>
                </>
              ) : (
                <>
                  <p className="text-sm font-medium text-slate-900">
                    Drag and drop a file here, or <span className="text-brand-600">click to choose</span>
                  </p>
                  <p className="mt-1 text-xs text-slate-500">PDF, TXT, PNG, JPG or JPEG</p>
                </>
              )}
            </div>

            <details className="group rounded-lg border border-slate-200 bg-white">
              <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-slate-700">
                Advanced: chunking options
              </summary>
              <div className="grid gap-4 border-t border-slate-100 p-4 sm:grid-cols-3">
                <Field label="Strategy">
                  <select value={strategy} onChange={(e) => setStrategy(e.target.value)} className={inputClass}>
                    <option value="fixed_size">fixed_size</option>
                    <option value="recursive">recursive</option>
                    <option value="sentence">sentence</option>
                  </select>
                </Field>
                <Field label="Chunk size">
                  <input
                    type="number"
                    value={chunkSize}
                    onChange={(e) => setChunkSize(Number(e.target.value))}
                    className={inputClass}
                  />
                </Field>
                <Field label="Overlap">
                  <input
                    type="number"
                    value={overlap}
                    onChange={(e) => setOverlap(Number(e.target.value))}
                    className={inputClass}
                  />
                </Field>
              </div>
            </details>

            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={handleUpload} disabled={!file} loading={loading}>
                {loading ? "Working (scanned files can take a minute)..." : "Upload"}
              </Button>
              <span className="text-xs text-slate-500">Uploading to {workspaceName}</span>
            </div>
          </div>
        </Card>

        <div className="space-y-4">
          <Card title="Status">
            {progress ? (
              <div className="flex items-start gap-2 text-sm text-slate-700">
                <Spinner className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
                <div className="min-w-0 space-y-1">
                  <p className="break-words">{progress}</p>
                  {jobState && <StatusBadge status={jobState} />}
                </div>
              </div>
            ) : result ? (
              <div className="space-y-4">
                <Alert tone={result.tone} title={result.title}>
                  <ul className="space-y-0.5">
                    {result.details.map((line, i) => (
                      <li key={i} className="break-words">
                        {line}
                      </li>
                    ))}
                  </ul>
                </Alert>
                {result.tone === "success" && (
                  <div className="flex flex-wrap gap-2">
                    <ButtonLink href="/documents" size="sm">
                      View documents
                    </ButtonLink>
                    <ButtonLink href="/chat" size="sm" variant="primary">
                      Chat with it
                    </ButtonLink>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-slate-500">Choose a file and press Upload. Progress appears here.</p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
