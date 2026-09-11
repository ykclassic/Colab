'use client';

import { getAccessToken } from './auth';

export const API = process.env.NEXT_PUBLIC_COLAB_API_URL ?? '/backend';

export type Strategy = { strategy_id: string; name: string; description: string; parameters: Record<string, unknown>; enabled: boolean };
export type Workspace = { workspace_id: string; name: string; product_goal: string; status: string; priority: number; strategies: Strategy[]; version: number; archived_at?: string | null; created_at: string; updated_at: string };
export type Metrics = { pending: number; running: number; succeeded: number; failed: number; retries: number };
export type Tool = { name: string; description: string };
export type Event = { event_type: string; level: string; actor: string; message: string; occurred_at?: string };

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getAccessToken();
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`${API}${path}`, { cache: 'no-store', ...init, headers });
  if (!response.ok) {
    let detail = `API request failed: ${response.status}`;
    try { const body = await response.json() as { detail?: string }; if (body.detail) detail = body.detail; } catch {}
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const getAuthMe = () => request<{ user_id: string; role: string; email: string | null; session_id: string | null }>('/api/auth/me');
export const getWorkspaces = (includeArchived = false) => request<Workspace[]>(`/api/workspaces?include_archived=${includeArchived}`);
export const createWorkspace = (payload: { name: string; product_goal: string; priority?: number; strategies?: Strategy[] }, idempotencyKey: string) => request<Workspace>('/api/workspaces', { method: 'POST', headers: { 'content-type': 'application/json', 'idempotency-key': idempotencyKey }, body: JSON.stringify(payload) });
export const updateWorkspace = (id: string, version: number, payload: { name: string; product_goal: string; priority: number; strategies: Strategy[] }) => request<Workspace>(`/api/workspaces/${id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ ...payload, version }) });
export const archiveWorkspace = (id: string, version: number) => request<Workspace>(`/api/workspaces/${id}/archive`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ version }) });
export const restoreWorkspace = (id: string, version: number) => request<Workspace>(`/api/workspaces/${id}/restore`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ version }) });
export const deleteWorkspace = (id: string, version: number) => request<void>(`/api/workspaces/${id}`, { method: 'DELETE', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ version }) });
export const getMetrics = () => request<Metrics>('/api/operations/metrics');
export const getEvents = () => request<Event[]>('/api/operations/events?limit=20');
export const getTools = () => request<Tool[]>('/api/tools');
