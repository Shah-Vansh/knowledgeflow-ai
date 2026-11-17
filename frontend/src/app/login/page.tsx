"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { Alert, Button, Field, inputClass } from "@/components/ui";
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
    <main className="flex min-h-screen bg-slate-50">
      <section className="relative hidden w-1/2 flex-col justify-between overflow-hidden bg-gradient-to-br from-brand-700 via-brand-600 to-indigo-500 p-12 text-white lg:flex">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/15 text-base font-bold ring-1 ring-white/30">K</span>
          <span className="text-lg font-semibold">KnowledgeFlow AI</span>
        </div>
        <div className="max-w-md">
          <h2 className="text-3xl font-semibold leading-tight tracking-tight">
            Answers from your own documents, with the sources to prove it.
          </h2>
          <ul className="mt-8 space-y-3 text-sm text-brand-50">
            <li>• Hybrid search, reranking and a knowledge graph</li>
            <li>• PDFs, scans, tables and images</li>
            <li>• Private workspaces with roles</li>
          </ul>
        </div>
        <p className="text-xs text-brand-100">Enterprise knowledge &amp; research copilot</p>
        <div className="pointer-events-none absolute -right-24 -top-24 h-80 w-80 rounded-full bg-white/10 blur-2xl" />
        <div className="pointer-events-none absolute -bottom-32 -left-16 h-96 w-96 rounded-full bg-indigo-300/20 blur-3xl" />
      </section>

      <section className="flex w-full items-center justify-center px-4 py-12 lg:w-1/2">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 text-base font-bold text-white">K</span>
            <span className="text-lg font-semibold text-slate-900">KnowledgeFlow AI</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            {mode === "login" ? "Welcome back" : "Create your account"}
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            {mode === "login" ? "Sign in to your workspaces." : "The first account becomes the owner of every workspace."}
          </p>

          {config && !config.auth_required && (
            <Alert tone="warning" className="mt-6">
              Sign-in is off on this server (AUTH_REQUIRED=false), so you don&apos;t need an account.{" "}
              <Link href="/" className="font-medium underline">Go to the app</Link>
            </Alert>
          )}

          <form onSubmit={onSubmit} className="mt-6 space-y-4">
            <Field label="Email">
              <input
                type="email"
                autoComplete="email"
                required
                className={inputClass}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
              />
            </Field>
            <Field
              label="Password"
              hint={mode === "register" && config ? `At least ${config.password_min_length} characters.` : undefined}
            >
              <input
                type="password"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                required
                minLength={mode === "register" ? config?.password_min_length ?? 10 : undefined}
                className={inputClass}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
            {error && <Alert tone="error">{error}</Alert>}
            <Button type="submit" loading={busy} className="w-full">
              {mode === "login" ? "Sign in" : "Create account"}
            </Button>
          </form>

          {config?.registration_open && (
            <p className="mt-6 text-center text-sm text-slate-500">
              {mode === "login" ? "No account yet?" : "Already have an account?"}{" "}
              <button
                type="button"
                className="font-medium text-brand-600 hover:text-brand-700"
                onClick={() => {
                  setMode(mode === "login" ? "register" : "login");
                  setError(null);
                }}
              >
                {mode === "login" ? "Register" : "Sign in"}
              </button>
            </p>
          )}
        </div>
      </section>
    </main>
  );
}
