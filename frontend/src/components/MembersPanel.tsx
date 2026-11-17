"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { getStoredEmail, isAuthRequired } from "@/lib/auth";
import { addMember, listMembers, Member, removeMember, Role, ROLES } from "@/lib/workspaces";
import { useWorkspace } from "@/lib/workspace-context";
import { Alert, Badge, Button, Card, Field, inputClass, Loading } from "@/components/ui";

const ROLE_HELP: Record<Role, string> = {
  viewer: "Ask questions, read documents",
  editor: "Also upload, delete and run evaluations",
  owner: "Also manage members and delete the workspace",
};

/** Members of the ACTIVE workspace. Only owners can change them; the API enforces it. */
export default function MembersPanel() {
  const { workspaceId, workspace } = useWorkspace();
  const [members, setMembers] = useState<Member[] | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const isOwner = workspace?.role === "owner";
  const me = getStoredEmail();

  const load = useCallback(async () => {
    try {
      setMembers(await listMembers(workspaceId));
      setError("");
    } catch (err) {
      setMembers([]);
      setError(err instanceof Error ? err.message : "Could not load members");
    }
  }, [workspaceId]);

  useEffect(() => {
    setMembers(null);
    setNotice("");
    load();
  }, [load]);

  if (!isAuthRequired()) {
    return (
      <Card title="Members" description="Who can use this workspace, and what they can do.">
        <p className="text-sm text-slate-500">
          Sign-in is off on this server, so everyone who can reach it has full access. Turn on{" "}
          <code className="rounded bg-slate-100 px-1 text-xs">AUTH_REQUIRED</code> to give people their own
          accounts and roles.
        </p>
      </Card>
    );
  }

  const run = async (action: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      setNotice(done);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  const onAdd = (event: FormEvent) => {
    event.preventDefault();
    const target = email.trim();
    if (!target) return;
    run(async () => {
      await addMember(workspaceId, target, role);
      setEmail("");
    }, `${target} is now a${role === "owner" ? "n" : ""} ${role}.`);
  };

  return (
    <Card
      title={`Members of ${workspace?.name ?? "this workspace"}`}
      description={isOwner ? "Add teammates by the email they registered with." : "Only owners can change members."}
    >
      <div className="space-y-4">
        {error && <Alert tone="error">{error}</Alert>}
        {notice && <Alert tone="success">{notice}</Alert>}

        {members === null ? (
          <Loading label="Loading members…" />
        ) : (
          <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
            {members.map((m) => (
              <li key={m.user_id} className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                <span className="flex min-w-0 items-center gap-2">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold uppercase text-slate-600">
                    {m.email[0]}
                  </span>
                  <span className="truncate text-sm text-slate-900">{m.email}</span>
                  {m.email === me && <Badge tone="brand">you</Badge>}
                </span>
                {isOwner ? (
                  <span className="flex items-center gap-2">
                    <select
                      aria-label={`Role of ${m.email}`}
                      value={m.role}
                      disabled={busy}
                      onChange={(e) => {
                        const next = e.target.value as Role;
                        run(() => addMember(workspaceId, m.email, next), `${m.email} is now a${next === "owner" ? "n" : ""} ${next}.`);
                      }}
                      className={`${inputClass} w-28 !py-1.5`}
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </select>
                    <Button
                      size="sm"
                      variant="danger"
                      disabled={busy}
                      onClick={() => {
                        if (window.confirm(`Remove ${m.email} from ${workspace?.name ?? "this workspace"}?`)) {
                          run(() => removeMember(workspaceId, m.user_id), `${m.email} was removed.`);
                        }
                      }}
                    >
                      Remove
                    </Button>
                  </span>
                ) : (
                  <Badge>{m.role}</Badge>
                )}
              </li>
            ))}
          </ul>
        )}

        {isOwner && (
          <form onSubmit={onAdd} className="grid gap-3 sm:grid-cols-[1fr_9rem_auto] sm:items-end">
            <Field label="Email">
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="teammate@company.com"
                className={inputClass}
              />
            </Field>
            <Field label="Role">
              <select value={role} onChange={(e) => setRole(e.target.value as Role)} className={inputClass}>
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </Field>
            <Button type="submit" loading={busy}>
              Add member
            </Button>
          </form>
        )}
        {isOwner && <p className="text-xs text-slate-500">{ROLE_HELP[role]}. They need an account first (Register on the sign-in page).</p>}
      </div>
    </Card>
  );
}
