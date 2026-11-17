const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Workspace {
  id: number;
  name: string;
  description: string | null;
  document_count: number;
  created_at: string | null;
}

async function errorMessage(response: Response, fallback: string): Promise<string> {
  const body = await response.json().catch(() => ({}));
  return typeof body.detail === "string" ? body.detail : `${fallback} (status ${response.status})`;
}

export async function listWorkspaces(): Promise<Workspace[]> {
  const response = await fetch(`${API_BASE_URL}/workspaces`, { cache: "no-store" });
  if (!response.ok) throw new Error(await errorMessage(response, "Failed to list workspaces"));
  return response.json();
}

export async function createWorkspace(name: string, description?: string): Promise<Workspace> {
  const response = await fetch(`${API_BASE_URL}/workspaces`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description: description?.trim() ? description : undefined }),
  });
  if (!response.ok) throw new Error(await errorMessage(response, "Failed to create workspace"));
  return response.json();
}

export async function deleteWorkspace(id: number): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/workspaces/${id}`, { method: "DELETE" });
  if (!response.ok) throw new Error(await errorMessage(response, "Failed to delete workspace"));
}
// ---------------------------------------------------------------- members
export type Role = "viewer" | "editor" | "owner";
export const ROLES: Role[] = ["viewer", "editor", "owner"];

export interface Member {
  user_id: number;
  email: string;
  role: Role;
  added_at: string | null;
}

export async function listMembers(workspaceId: number): Promise<Member[]> {
  const response = await fetch(`${API_BASE_URL}/workspaces/${workspaceId}/members`, { cache: "no-store" });
  if (!response.ok) throw new Error(await errorMessage(response, "Failed to list members"));
  return response.json();
}

/** Adds a registered user, or changes an existing member's role. */
export async function addMember(workspaceId: number, email: string, role: Role): Promise<Member> {
  const response = await fetch(`${API_BASE_URL}/workspaces/${workspaceId}/members`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, role }),
  });
  if (!response.ok) throw new Error(await errorMessage(response, "Failed to add member"));
  return response.json();
}

export async function removeMember(workspaceId: number, userId: number): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/workspaces/${workspaceId}/members/${userId}`, {
    method: "DELETE",
  });
  if (!response.ok) throw new Error(await errorMessage(response, "Failed to remove member"));
}
