const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface HealthResponse {
  status: string;
  db_connected: boolean;
  environment: string;
  error?: string;
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`, {
    cache: "no-store",
  });

  const data = (await response.json()) as HealthResponse;

  if (!response.ok && !data) {
    throw new Error(`Health check failed with status ${response.status}`);
  }

  return data;
}