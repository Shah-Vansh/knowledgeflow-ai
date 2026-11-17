"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { createWorkspace, deleteWorkspace } from "@/lib/workspaces";
import { useWorkspace, WorkspaceWithRole } from "@/lib/workspace-context";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  Loading,
  PageHeader,
  inputClass,
} from "@/components/ui";
import { LayersIcon } from "@/components/icons";

export default function WorkspacesPage() {
  const { workspaces, workspaceId, setWorkspaceId, refresh, loading, error: loadError } = useWorkspace();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const handleCreate = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const created = await createWorkspace(name.trim(), description);
      setName("");
      setDescription("");
      await refresh();
      setWorkspaceId(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create workspace");
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (w: WorkspaceWithRole) => {
    if (
      !window.confirm(
        `Delete workspace "${w.name}" (${w.document_count} document(s))? This cannot be undone.`
      )
    )
      return;
    setError("");
    setDeletingId(w.id);
    try {
      await deleteWorkspace(w.id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete workspace");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Workspaces"
        description="Each workspace is an isolated knowledge space. Documents, chats and retrieval never cross workspace boundaries."
      />

      {(error || loadError) && <Alert tone="error">{error || loadError}</Alert>}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="New workspace" description="Create a space and switch to it." className="lg:self-start">
          <form onSubmit={handleCreate} className="space-y-4">
            <Field label="Name">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Engineering"
                className={inputClass}
                maxLength={80}
              />
            </Field>
            <Field label="Description" hint="Optional">
              <input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What lives in this workspace?"
                className={inputClass}
                maxLength={500}
              />
            </Field>
            <Button type="submit" className="w-full" disabled={!name.trim()} loading={busy}>
              {busy ? "Creating..." : "Create workspace"}
            </Button>
          </form>
        </Card>

        <div className="lg:col-span-2">
          {loading ? (
            <Loading label="Loading workspaces…" />
          ) : workspaces.length === 0 ? (
            <EmptyState
              icon={<LayersIcon className="h-8 w-8" />}
              title="No workspaces"
              description="Create your first workspace with the form."
            />
          ) : (
            <Card title="All workspaces" padded={false}>
              <ul className="divide-y divide-slate-100">
                {workspaces.map((w) => {
                  const active = w.id === workspaceId;
                  return (
                    <li key={w.id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="font-medium text-slate-900 break-all">{w.name}</p>
                          <span className="text-xs text-slate-400">#{w.id}</span>
                          {active && <Badge tone="brand">Active</Badge>}
                          {w.role && <Badge>{w.role}</Badge>}
                        </div>
                        {w.description && <p className="mt-0.5 text-sm text-slate-600">{w.description}</p>}
                        <p className="mt-0.5 text-xs text-slate-500">{w.document_count} document(s)</p>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={active}
                          onClick={() => setWorkspaceId(w.id)}
                        >
                          {active ? "Current" : "Switch to"}
                        </Button>
                        {w.id !== 1 && (
                          <Button
                            size="sm"
                            variant="danger"
                            loading={deletingId === w.id}
                            onClick={() => handleDelete(w)}
                          >
                            Delete
                          </Button>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
