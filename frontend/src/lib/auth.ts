// Phase 15: client-side auth helpers.
//
// The access token lives in localStorage. Trade-off: any script running on this
// origin (i.e. an XSS bug) could read it. An httpOnly cookie would hide it from
// scripts but needs CSRF protection and a same-site backend; for this project the
// backend never returns HTML, answers are sanitized server-side, and React escapes
// everything it renders, which keeps the XSS surface small. Tokens also expire
// (JWT_EXPIRE_MINUTES), limiting the damage of a leaked one.

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TOKEN_KEY = "kf_token";
const EXPIRES_KEY = "kf_token_expires_at";
const EMAIL_KEY = "kf_email";
const WORKSPACE_KEY = "kf_active_workspace";

export interface AuthConfig {
  auth_required: boolean;
  registration_open: boolean;
  password_min_length: number;
}

export interface AuthUser {
  id: number;
  email: string;
  created_at: string | null;
  last_login_at: string | null;
  workspaces?: { workspace_id: number; role: string }[];
}

interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: AuthUser;
}

let authRequiredFlag = false;

export function setAuthRequired(value: boolean) {
  authRequiredFlag = value;
}

export function isAuthRequired(): boolean {
  return authRequiredFlag;
}

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  const s = storage();
  if (!s) return null;
  const token = s.getItem(TOKEN_KEY);
  const expires = Number(s.getItem(EXPIRES_KEY) || 0);
  if (!token) return null;
  if (expires && Date.now() > expires) {
    clearSession();
    return null;
  }
  return token;
}

export function getStoredEmail(): string | null {
  return storage()?.getItem(EMAIL_KEY) ?? null;
}

function saveSession(data: TokenResponse) {
  const s = storage();
  if (!s) return;
  s.setItem(TOKEN_KEY, data.access_token);
  s.setItem(EXPIRES_KEY, String(Date.now() + data.expires_in * 1000 - 30_000));
  s.setItem(EMAIL_KEY, data.user.email);
}

export function clearSession() {
  const s = storage();
  if (!s) return;
  s.removeItem(TOKEN_KEY);
  s.removeItem(EXPIRES_KEY);
  s.removeItem(EMAIL_KEY);
}

// ---------------------------------------------------------------- active workspace
// The active workspace is chosen once, in the sidebar, and shared by every page.
export function getActiveWorkspaceId(): number | null {
  const raw = storage()?.getItem(WORKSPACE_KEY);
  const id = raw ? Number(raw) : NaN;
  return Number.isInteger(id) && id > 0 ? id : null;
}

export function setActiveWorkspaceId(id: number) {
  storage()?.setItem(WORKSPACE_KEY, String(id));
}

/**
 * The workspace picked in the sidebar switcher. Every page works inside it, with
 * auth on or off, so calls that don't name a workspace use this one (1 = General).
 */
export function workspaceForUnscopedCall(): number | undefined {
  return getActiveWorkspaceId() ?? 1;
}

// ---------------------------------------------------------------- API calls
async function detail(response: Response, fallback: string): Promise<string> {
  const body = await response.json().catch(() => ({}));
  return typeof body.detail === "string" ? body.detail : `${fallback} (status ${response.status})`;
}

export async function getAuthConfig(): Promise<AuthConfig> {
  const response = await fetch(`${API_BASE_URL}/auth/config`, { cache: "no-store" });
  if (!response.ok) throw new Error(await detail(response, "Could not read auth config"));
  return response.json();
}

async function credentialsCall(path: string, email: string, password: string): Promise<AuthUser> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) throw new Error(await detail(response, "Request failed"));
  const data = (await response.json()) as TokenResponse;
  saveSession(data);
  return data.user;
}

export const login = (email: string, password: string) => credentialsCall("/auth/login", email, password);
export const register = (email: string, password: string) => credentialsCall("/auth/register", email, password);

export async function me(): Promise<AuthUser> {
  const response = await fetch(`${API_BASE_URL}/auth/me`, { cache: "no-store" });
  if (!response.ok) throw new Error(await detail(response, "Not signed in"));
  return response.json();
}

export function logout() {
  clearSession();
  if (typeof window !== "undefined") window.location.href = "/login";
}

/** Revokes every token for this account (all browsers and devices), then signs out here. */
export async function logoutEverywhere() {
  try {
    await fetch(`${API_BASE_URL}/auth/logout-all`, { method: "POST" });
  } finally {
    logout();
  }
}

/** Only same-site relative paths, so ?next= can't send the user to another site. */
export function safeNextPath(raw: string | null): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return "/";
  return raw;
}

// ---------------------------------------------------------------- fetch patch
let patched = false;

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

/**
 * Wraps window.fetch once: API calls get "Authorization: Bearer <token>", and a 401
 * from the API (outside the login form) clears the session and goes to /login.
 */
export function installAuthFetch() {
  if (patched || typeof window === "undefined") return;
  patched = true;
  const original = window.fetch.bind(window);

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = requestUrl(input);
    if (!url.startsWith(API_BASE_URL)) return original(input, init);

    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
    const token = getToken();
    if (token && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
    const response = await original(input, { ...init, headers });

    const path = url.slice(API_BASE_URL.length);
    const isCredentialCall = path.startsWith("/auth/login") || path.startsWith("/auth/register");
    if (response.status === 401 && authRequiredFlag && !isCredentialCall) {
      clearSession();
      if (window.location.pathname !== "/login") {
        const next = encodeURIComponent(window.location.pathname + window.location.search);
        window.location.href = `/login?next=${next}`;
      }
    }
    return response;
  };
}
