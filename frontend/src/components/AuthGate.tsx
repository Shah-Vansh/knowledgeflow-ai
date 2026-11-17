"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import AppShell from "@/components/AppShell";
import { Loading } from "@/components/ui";
import { getAuthConfig, getToken, installAuthFetch, logout, me, setAuthRequired } from "@/lib/auth";
import { WorkspaceProvider } from "@/lib/workspace-context";

type State =
  | { kind: "loading" }
  | { kind: "open" } // auth off (or backend unreachable): pages behave as before
  | { kind: "signed-in"; email: string };

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [state, setState] = useState<State>({ kind: "loading" });
  const onLoginPage = pathname === "/login";

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
      if (onLoginPage) {
        if (!cancelled) setState({ kind: "open" });
        return;
      }
      if (!getToken()) {
        window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
        return;
      }
      try {
        const user = await me();
        if (!cancelled) setState({ kind: "signed-in", email: user.email });
      } catch {
        logout();
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [onLoginPage]); // re-check only when entering or leaving /login

  if (onLoginPage) return <>{children}</>;
  if (state.kind === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loading label="Starting KnowledgeFlow…" />
      </div>
    );
  }
  return (
    <WorkspaceProvider>
      <AppShell email={state.kind === "signed-in" ? state.email : null}>{children}</AppShell>
    </WorkspaceProvider>
  );
}
