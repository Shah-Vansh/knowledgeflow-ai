import { APIRequestContext, expect, Page, request } from "@playwright/test";

export const API = process.env.E2E_API ?? "http://localhost:8000";
export const PASSWORD = "E2e-Granite-Harbor-58";

export interface Session {
  email: string;
  token: string;
  userId: number;
  workspaceId: number;
  workspaceName: string;
}

const unique = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;

export async function api(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: API });
}

/** Registers a fresh user (or logs in) and gives them their own new workspace. */
export async function newSession(label = "user"): Promise<Session> {
  const ctx = await api();
  const email = `e2e-${label}-${unique()}@kf-e2e.test`;
  const reg = await ctx.post("/auth/register", { data: { email, password: PASSWORD } });
  expect(reg.status(), await reg.text()).toBe(201);
  const body = await reg.json();
  const token: string = body.access_token;
  const workspaceName = `E2E ${label} ${unique()}`;
  const ws = await ctx.post("/workspaces", {
    data: { name: workspaceName },
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(ws.status(), await ws.text()).toBe(201);
  const workspace = await ws.json();
  await ctx.dispose();
  return { email, token, userId: body.user.id, workspaceId: workspace.id, workspaceName };
}

/** Puts the session into localStorage before any page script runs. */
export async function signIn(page: Page, session: Session) {
  await page.addInitScript((s) => {
    // only on the first page load of this tab, so logging out really logs out
    if (sessionStorage.getItem("kf_e2e_seeded")) return;
    sessionStorage.setItem("kf_e2e_seeded", "1");
    localStorage.setItem("kf_token", s.token);
    localStorage.setItem("kf_token_expires_at", String(Date.now() + 50 * 60 * 1000));
    localStorage.setItem("kf_email", s.email);
    localStorage.setItem("kf_active_workspace", String(s.workspaceId));
  }, session);
}

export async function uploadViaApi(session: Session, name: string, text: string) {
  const ctx = await api();
  const res = await ctx.post("/documents/upload", {
    headers: { Authorization: `Bearer ${session.token}` },
    multipart: {
      file: { name, mimeType: "text/plain", buffer: Buffer.from(text) },
      workspace_id: String(session.workspaceId),
    },
  });
  expect([200, 202]).toContain(res.status());
  const body = await res.json();
  if (body.job_id) {
    // queued: wait for the worker
    for (let i = 0; i < 90; i++) {
      const job = await (await ctx.get(`/jobs/${body.job_id}`, {
        headers: { Authorization: `Bearer ${session.token}` },
      })).json();
      if (["succeeded", "failed", "cancelled"].includes(job.status)) break;
      await new Promise((r) => setTimeout(r, 1000));
    }
  }
  await ctx.dispose();
  return body.document_id as number;
}
