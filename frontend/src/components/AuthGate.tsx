"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import {
  API_BASE_URL,
  getActiveWorkspaceId,
  getAuthConfig,
  getToken,
  installAuthFetch,
  logout,
  me,
  setActiveWorkspaceId,
  setAuthRequired,
} from "@/lib/auth";

interface WorkspaceOption {
  id: number;
  name: string;
  role: string | null;
}

type State =
  | { kind: "loading" }
  | { kind: "open" } // auth off (or backend unreachable): pages behave as before
  | { kind: "signed-in"; email: string; workspaces: WorkspaceOption[] };

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    installAuthFetch(); // before any child page mounts and fetches
    let cancelled = false;

    (async () => {
      let required = false;
      try {
        required = (await getAuthConfig()).auth_required;
      } catch {
        // backend unreachable: let the page render and show its own error
      }
      setAuthRequired(required);
      if (!required) {
        if (!cancelled) setState({ kind: "open" });
        return;
      }
      if (pathname === "/login") {
        if (!cancelled) setState({ kind: "open" });
        return;
      }
      if (!getToken()) {
        window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
        return;
      }
      try {
        const user = await me();
        const response = await fetch(`${API_BASE_URL}/workspaces`, { cache: "no-store" });
        const workspaces: WorkspaceOption[] = response.ok ? await response.json() : [];
        const active = getActiveWorkspaceId();
        if (workspaces.length > 0 && !workspaces.some((w) => w.id === active)) {
          setActiveWorkspaceId(workspaces[0].id);
        }
        if (!cancelled) setState({ kind: "signed-in", email: user.email, workspaces });
      } catch {
        logout();
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [pathname]);

  if (state.kind === "loading") {
    return <div className="p-8 text-sm text-gray-500">Loading…</div>;
  }
  if (state.kind === "open") return <>{children}</>;

  const active = getActiveWorkspaceId();
  return (
    <>
      <div className="flex flex-wrap items-center justify-end gap-3 border-b bg-white px-4 py-2 text-sm">
        {state.workspaces.length > 0 ? (
          <label className="flex items-center gap-2">
            <span className="text-gray-500">Workspace</span>
            <select
              className="rounded border px-2 py-1"
              value={active ?? ""}
              onChange={(e) => {
                setActiveWorkspaceId(Number(e.target.value));
                window.location.reload();
              }}
            >
              {state.workspaces.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                  {w.role ? ` (${w.role})` : ""}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <span className="text-gray-500">No workspaces yet — create one or ask an owner to add you</span>
        )}
        <span className="text-gray-700">{state.email}</span>
        <button className="rounded border px-3 py-1 hover:bg-gray-100" onClick={logout}>
          Log out
        </button>
      </div>
      {children}
    </>
  );
}
