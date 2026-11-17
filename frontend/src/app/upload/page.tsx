"use client";

import { useEffect, useRef, useState } from "react";
import { IngestReport, JobStatus, uploadDocument, waitForJob } from "@/lib/documents";
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
  const unmounted = useRef(false);

  useEffect(() => {
    unmounted.current = false;
    return () => {
      unmounted.current = true;
    };
  }, []);

  useEffect(() => {
    listWorkspaces()
      .then((list) => {
        setWorkspaces(list);
        if (list.length > 0 && !list.some((w) => w.id === 1)) setWorkspaceId(list[0].id);
      })
      .catch(() => {});
  }, []);

  const describe = (
    filename: string,
    wsId: number,
    docStatus: string,
    documentId: number,
    report: IngestReport | null
  ) => {
    const where = workspaces.find((w) => w.id === wsId)?.name ?? `#${wsId}`;
    const found = report
      ? [
          report.pages_ocr > 0 ? `${report.pages_ocr} page(s) read with OCR` : "",
          report.tables > 0 ? `${report.tables} table(s)` : "",
          report.images_ocr > 0 ? `${report.images_ocr} image(s) with text` : "",
        ].filter(Boolean)
      : [];
    return (
      `Uploaded "${filename}" to workspace "${where}" — status: ${docStatus} (document_id: ${documentId})` +
      (found.length > 0 ? ` — found: ${found.join(", ")}` : "") +
      (report && report.notes.length > 0 ? ` — note: ${report.notes[0]}` : "")
    );
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
    setStatus("");
    try {
      const result = await uploadDocument(
        file,
        { strategy, chunk_size: chunkSize, overlap },
        workspaceId
      );
      if (result.job_id == null) {
        setStatus(
          describe(result.filename, result.workspace_id, result.status, result.document_id, result.ingest_report)
        );
        return;
      }

      setStatus(`Uploaded "${result.filename}" — queued for processing (job ${result.job_id})`);
      const job = await waitForJob(
        result.job_id,
        (update) => {
          if (!unmounted.current) setStatus(`"${result.filename}": ${jobProgress(update)}`);
        },
        undefined,
        () => unmounted.current
      );
      if (unmounted.current) return;
      if (job.status === "succeeded" && job.document) {
        setStatus(
          describe(job.document.filename, job.workspace_id, job.document.status, job.document.id, job.document.ingest_report)
        );
      } else if (job.status === "cancelled") {
        setStatus(`"${result.filename}" was not processed: ${job.last_error ?? "cancelled"}`);
      } else {
        setStatus(`"${result.filename}" failed: ${job.last_error ?? "processing failed"}`);
      }
    } catch (err) {
      if (!unmounted.current) setStatus(err instanceof Error ? err.message : "Upload failed");
    } finally {
      if (!unmounted.current) setLoading(false);
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
          accept=".pdf,.txt,.png,.jpg,.jpeg"
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
          {loading ? "Working (scanned files can take a minute)..." : "Upload"}
        </button>
        {status && (
          <div className="rounded-lg border border-gray-300 p-3 text-sm bg-white">{status}</div>
        )}
        <div className="flex flex-wrap justify-between gap-2 text-sm">
          <a href="/chat" className="text-blue-600 underline">
            Chat →
          </a>
          <a href="/inspector" className="text-blue-600 underline">
            Inspector →
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