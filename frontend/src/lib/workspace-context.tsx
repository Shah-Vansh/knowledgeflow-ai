"use client";

/**
 * One active workspace for the whole app. The sidebar switcher changes it and
 * every page reads it with useWorkspace(), so pages no longer need their own
 * workspace dropdowns and nothing has to reload when you switch.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { getActiveWorkspaceId, setActiveWorkspaceId } from "@/lib/auth";
import { listWorkspaces, Workspace } from "@/lib/workspaces";

export type WorkspaceWithRole = Workspace & { role?: string | null };

interface WorkspaceState {
  workspaces: WorkspaceWithRole[];
  /** The active workspace id (falls back to General = 1 until the list loads). */
  workspaceId: number;
  workspace: WorkspaceWithRole | null;
  loading: boolean;
  error: string;
  setWorkspaceId: (id: number) => void;
  refresh: () => Promise<WorkspaceWithRole[]>;
}

const WorkspaceContext = createContext<WorkspaceState | null>(null);

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const [workspaces, setWorkspaces] = useState<WorkspaceWithRole[]>([]);
  // Starts at 1 so the server render matches; refresh() applies the stored choice before
  // the shell renders any page (AppShell waits for `loading` to clear).
  const [workspaceId, setId] = useState<number>(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const list = (await listWorkspaces()) as WorkspaceWithRole[];
      setWorkspaces(list);
      setError("");
      const stored = getActiveWorkspaceId();
      const valid = list.find((w) => w.id === stored) ?? list.find((w) => w.id === 1) ?? list[0];
      if (valid) {
        setId(valid.id);
        setActiveWorkspaceId(valid.id);
      }
      return list;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load workspaces");
      return [];
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const setWorkspaceId = useCallback((id: number) => {
    setActiveWorkspaceId(id);
    setId(id);
  }, []);

  const value = useMemo<WorkspaceState>(
    () => ({
      workspaces,
      workspaceId,
      workspace: workspaces.find((w) => w.id === workspaceId) ?? null,
      loading,
      error,
      setWorkspaceId,
      refresh,
    }),
    [workspaces, workspaceId, loading, error, setWorkspaceId, refresh]
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceState {
  const context = useContext(WorkspaceContext);
  if (!context) throw new Error("useWorkspace must be used inside <WorkspaceProvider>");
  return context;
}
