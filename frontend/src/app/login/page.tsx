"use client";

import { FormEvent, useEffect, useState } from "react";
import { AuthConfig, getAuthConfig, login, register, safeNextPath } from "@/lib/auth";

export default function LoginPage() {
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getAuthConfig()
      .then(setConfig)
      .catch(() => setError("Backend unreachable"));
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password);
      const next = safeNextPath(new URLSearchParams(window.location.search).get("next"));
      window.location.href = next === "/login" ? "/" : next;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto mt-16 max-w-sm rounded-lg border bg-white p-6 shadow-sm">
      <h1 className="mb-1 text-xl font-semibold">KnowledgeFlow AI</h1>
      <p className="mb-6 text-sm text-gray-500">
        {mode === "login" ? "Sign in to your workspaces" : "Create an account"}
      </p>

      {config && !config.auth_required && (
        <p className="mb-4 rounded bg-yellow-50 p-2 text-sm text-yellow-800">
          Authentication is off on this server (AUTH_REQUIRED=false); you don&apos;t need to sign in.
        </p>
      )}

      <form onSubmit={onSubmit} className="space-y-4">
        <label className="block text-sm">
          Email
          <input
            type="email"
            autoComplete="email"
            required
            className="mt-1 w-full rounded border px-3 py-2"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label className="block text-sm">
          Password
          <input
            type="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
            minLength={mode === "register" ? config?.password_min_length ?? 10 : undefined}
            className="mt-1 w-full rounded border px-3 py-2"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {mode === "register" && config && (
          <p className="text-xs text-gray-500">At least {config.password_min_length} characters.</p>
        )}
        {error && <p className="rounded bg-red-50 p-2 text-sm text-red-700">{error}</p>}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded bg-blue-600 px-4 py-2 font-medium text-white disabled:opacity-50"
        >
          {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
        </button>
      </form>

      {config?.registration_open && (
        <button
          className="mt-4 text-sm text-blue-600 hover:underline"
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError(null);
          }}
        >
          {mode === "login" ? "No account? Register" : "Have an account? Sign in"}
        </button>
      )}
    </main>
  );
}
