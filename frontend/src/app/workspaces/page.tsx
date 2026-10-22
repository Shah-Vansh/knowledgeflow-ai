"use client";

import { useEffect, useState } from "react";
import {
  createWorkspace,
  deleteWorkspace,
  listWorkspaces,
  Workspace,
} from "@/lib/workspaces";

export default function WorkspacesPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    listWorkspaces()
      .then(setWorkspaces)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load workspaces"));
  };

  useEffect(() => {
    load();
  }, []);

  const handleCreate = async () => {
    if (!name.trim()) return;
    setBusy(true);
    setError("");
    try {
      await createWorkspace(name.trim(), description);
      setName("");
      setDescription("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create workspace");
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (id: number) => {
    setError("");
    try {
      await deleteWorkspace(id);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete workspace");
    }
  };

  return (
    <main className="min-h-screen p-8 flex flex-col items-center">
      <h1 className="text-2xl font-bold mb-2">Workspaces</h1>
      <p className="text-sm text-gray-500 mb-6 text-center max-w-lg">
        Each workspace is an isolated knowledge space. Documents, chats and retrieval never cross
        workspace boundaries.
      </p>

      <div className="w-full max-w-2xl space-y-4">
        <div className="border border-gray-300 rounded-lg p-3 bg-white space-y-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="New workspace name (e.g. Engineering)"
            className="w-full border border-gray-300 rounded p-2 text-sm"
            maxLength={80}
          />
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Description (optional)"
            className="w-full border border-gray-300 rounded p-2 text-sm"
            maxLength={500}
          />
          <button
            onClick={handleCreate}
            disabled={!name.trim() || busy}
            className="w-full bg-blue-600 text-white rounded-lg py-2 text-sm disabled:opacity-50"
          >
            {busy ? "Creating..." : "Create workspace"}
          </button>
        </div>

        {error && <div className="text-red-600 text-sm">{error}</div>}

        {workspaces.map((w) => (
          <div
            key={w.id}
            className="border border-gray-300 rounded-lg p-3 bg-white flex items-center justify-between"
          >
            <div className="text-sm">
              <p className="font-medium">
                #{w.id} — {w.name}
              </p>
              <p className="text-gray-500">
                {w.document_count} document(s)
                {w.description ? ` · ${w.description}` : ""}
              </p>
            </div>
            {w.id !== 1 && (
              <button
                onClick={() => handleDelete(w.id)}
                className="text-red-600 border border-red-300 rounded px-3 py-1 text-sm"
              >
                Delete
              </button>
            )}
          </div>
        ))}

        <div className="flex justify-between text-sm pt-2">
          <a href="/upload" className="text-blue-600 underline">
            ← Upload
          </a>
          <a href="/chat" className="text-blue-600 underline">
            Chat →
          </a>
        </div>
      </div>
    </main>
  );
}