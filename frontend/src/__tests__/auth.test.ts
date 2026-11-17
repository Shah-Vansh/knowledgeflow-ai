import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const API = "http://localhost:8000";

async function freshAuth() {
  vi.resetModules();
  return import("@/lib/auth");
}

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState(null, "", "/documents?x=1");
});
afterEach(() => vi.unstubAllGlobals());

describe("safeNextPath", () => {
  it.each([
    [null, "/"],
    ["", "/"],
    ["/chat", "/chat"],
    ["/documents?workspace=2", "/documents?workspace=2"],
    ["https://evil.example", "/"],
    ["//evil.example", "/"],
    [String.raw`/\evil.example`, "/"],
    ["javascript:alert(1)", "/"],
  ])("%s -> %s", async (raw, expected) => {
    const { safeNextPath } = await freshAuth();
    expect(safeNextPath(raw)).toBe(expected);
  });
});

describe("session storage", () => {
  it("returns the token until it expires, then clears it", async () => {
    const auth = await freshAuth();
    localStorage.setItem("kf_token", "abc");
    localStorage.setItem("kf_token_expires_at", String(Date.now() + 60_000));
    expect(auth.getToken()).toBe("abc");
    localStorage.setItem("kf_token_expires_at", String(Date.now() - 1));
    expect(auth.getToken()).toBeNull();
    expect(localStorage.getItem("kf_token")).toBeNull();
  });

  it("uses the active workspace for unscoped calls, General (1) by default", async () => {
    const auth = await freshAuth();
    expect(auth.workspaceForUnscopedCall()).toBe(1);
    auth.setActiveWorkspaceId(7);
    expect(auth.getActiveWorkspaceId()).toBe(7);
    expect(auth.workspaceForUnscopedCall()).toBe(7);
    localStorage.setItem("kf_active_workspace", "not-a-number");
    expect(auth.getActiveWorkspaceId()).toBeNull();
  });
});

describe("installAuthFetch", () => {
  function stubFetch(status: number) {
    const calls: Array<{ url: string; headers: Headers }> = [];
    const fake = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), headers: new Headers(init?.headers) });
      return new Response("{}", { status });
    });
    vi.stubGlobal("fetch", fake);
    window.fetch = fake as typeof window.fetch;
    return calls;
  }

  it("adds the bearer token to API calls only", async () => {
    const calls = stubFetch(200);
    const auth = await freshAuth();
    localStorage.setItem("kf_token", "tok-1");
    auth.installAuthFetch();
    await window.fetch(`${API}/documents`);
    await window.fetch("https://other.example/data");
    expect(calls[0].headers.get("Authorization")).toBe("Bearer tok-1");
    expect(calls[1].headers.get("Authorization")).toBeNull();
  });

  it("on a 401 with auth on, clears the session and sends you to /login with next", async () => {
    stubFetch(401);
    const auth = await freshAuth();
    localStorage.setItem("kf_token", "expired");
    auth.setAuthRequired(true);
    auth.installAuthFetch();
    const assigned: string[] = [];
    const location = { ...window.location, pathname: "/documents", search: "?x=1" };
    Object.defineProperty(location, "href", { set: (v: string) => assigned.push(v), get: () => "" });
    vi.stubGlobal("location", location);
    Object.defineProperty(window, "location", { value: location, configurable: true });

    await window.fetch(`${API}/workspaces`);
    expect(localStorage.getItem("kf_token")).toBeNull();
    expect(assigned).toEqual(["/login?next=%2Fdocuments%3Fx%3D1"]);
  });

  it("does not redirect when the login form itself gets a 401", async () => {
    stubFetch(401);
    const auth = await freshAuth();
    auth.setAuthRequired(true);
    auth.installAuthFetch();
    localStorage.setItem("kf_token", "keep");
    await window.fetch(`${API}/auth/login`, { method: "POST" });
    expect(localStorage.getItem("kf_token")).toBe("keep");
  });
});
