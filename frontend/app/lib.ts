export const API = process.env.NEXT_PUBLIC_COLAB_API_URL ?? '/backend';

export type Workspace = { workspace_id: string; name: string; product_goal: string; status: string; priority: number; strategies: unknown[] };
export type Metrics = { pending: number; running: number; succeeded: number; failed: number; retries: number };
export type Tool = { name: string; description: string };
export type Event = { event_type: string; level: string; actor: string; message: string; occurred_at?: string };

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`, { cache: 'no-store' });
  if (!response.ok) throw new Error(`API request failed: ${response.status}`);
  return response.json() as Promise<T>;
}

export const getWorkspaces = () => request<Workspace[]>('/api/workspaces');
export const getMetrics = () => request<Metrics>('/api/operations/metrics');
export const getEvents = () => request<Event[]>('/api/operations/events?limit=20');
export const getTools = () => request<Tool[]>('/api/tools');
