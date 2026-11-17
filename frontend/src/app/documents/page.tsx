"use client";

import { useCallback, useEffect, useState } from "react";
import { listDocuments, deleteDocument, DocumentSummary } from "@/lib/documents";
import { useWorkspace } from "@/lib/workspace-context";
import {
  Alert,
  Button,
  ButtonLink,
  Card,
  EmptyState,
  Loading,
  PageHeader,
  StatusBadge,
} from "@/components/ui";
import { DocumentsIcon, UploadIcon } from "@/components/icons";

export default function DocumentsPage() {
  const { workspaceId, workspace, refresh } = useWorkspace();
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const load = useCallback(() => {
    return listDocuments(undefined, workspaceId)
      .then((list) => {
        setDocuments(list);
        setError("");
      })
      .catch(() => setError("Could not load documents"))
      .finally(() => setLoading(false));
  }, [workspaceId]);

  useEffect(() => {
    setLoading(true);
    setDocuments([]);
    load();
  }, [load]);

  const handleDelete = async (doc: DocumentSummary) => {
    if (!window.confirm(`Delete "${doc.filename}"? Its chunks will be removed from search.`)) return;
    setDeletingId(doc.id);
    setError("");
    try {
      await deleteDocument(doc.id);
      await load();
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Documents"
        description={`Files uploaded to ${workspace?.name ?? "this workspace"}. Deleting a document removes it and its chunks from retrieval.`}
        actions={
          <ButtonLink href="/upload" variant="primary">
            <UploadIcon className="h-4 w-4" />
            Upload
          </ButtonLink>
        }
      />

      {error && <Alert tone="error">{error}</Alert>}

      {loading ? (
        <Loading label="Loading documents…" />
      ) : documents.length === 0 ? (
        <EmptyState
          icon={<DocumentsIcon className="h-8 w-8" />}
          title="No documents here yet"
          description={`Upload a PDF, text file or image to ${workspace?.name ?? "this workspace"} to start asking questions about it.`}
          action={
            <ButtonLink href="/upload" variant="primary">
              Upload a document
            </ButtonLink>
          }
        />
      ) : (
        <Card padded={false}>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
                  <th className="px-5 py-3">Filename</th>
                  <th className="px-3 py-3">Status</th>
                  <th className="px-3 py-3">Type</th>
                  <th className="px-3 py-3">Pages</th>
                  <th className="px-3 py-3">Uploaded</th>
                  <th className="px-5 py-3 text-right">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {documents.map((d) => (
                  <tr key={d.id} className="hover:bg-slate-50">
                    <td className="px-5 py-3">
                      <p className="font-medium text-slate-900 break-all">{d.filename}</p>
                      <p className="text-xs text-slate-500">#{d.id}</p>
                    </td>
                    <td className="px-3 py-3">
                      <StatusBadge status={d.status} />
                    </td>
                    <td className="px-3 py-3 text-slate-600">{d.source_type ?? "—"}</td>
                    <td className="px-3 py-3 tabular-nums text-slate-600">{d.page_count ?? "—"}</td>
                    <td className="whitespace-nowrap px-3 py-3 text-slate-600">
                      {d.uploaded_at ? new Date(d.uploaded_at).toLocaleString() : "—"}
                    </td>
                    <td className="px-5 py-3 text-right">
                      <Button
                        variant="danger"
                        size="sm"
                        loading={deletingId === d.id}
                        onClick={() => handleDelete(d)}
                      >
                        {deletingId === d.id ? "Deleting..." : "Delete"}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
