-- Phase 19 Agent Platform
create table if not exists public.agents (
  agent_id uuid primary key,
  workspace_id uuid not null references public.product_workspaces(workspace_id) on delete cascade,
  name text not null,
  version integer not null check (version > 0),
  role text not null,
  code_revision text not null,
  model text not null,
  tools text[] not null default '{}',
  configuration jsonb not null default '{}',
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  unique (workspace_id, name, version)
);
create index if not exists agents_workspace_idx on public.agents(workspace_id);

create table if not exists public.agent_evaluations (
  result_id uuid primary key,
  case_id uuid not null,
  agent_id uuid not null references public.agents(agent_id) on delete cascade,
  workspace_id uuid not null references public.product_workspaces(workspace_id) on delete cascade,
  score double precision not null check (score between 0 and 1),
  correctness double precision not null check (correctness between 0 and 1),
  evidence_quality double precision not null check (evidence_quality between 0 and 1),
  latency_ms double precision not null check (latency_ms >= 0),
  tokens_in bigint not null default 0 check (tokens_in >= 0),
  tokens_out bigint not null default 0 check (tokens_out >= 0),
  cost_usd double precision not null default 0 check (cost_usd >= 0),
  passed boolean not null,
  rationale text not null,
  created_at timestamptz not null default now()
);
create index if not exists agent_evaluations_workspace_agent_idx on public.agent_evaluations(workspace_id, agent_id, created_at);

create table if not exists public.agent_memory (
  memory_id uuid primary key,
  workspace_id uuid not null references public.product_workspaces(workspace_id) on delete cascade,
  agent_id uuid references public.agents(agent_id) on delete cascade,
  key text not null,
  value text not null,
  source text not null,
  confidence double precision not null default 1 check (confidence between 0 and 1),
  expires_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists agent_memory_workspace_idx on public.agent_memory(workspace_id, created_at desc);

create table if not exists public.agent_costs (
  record_id uuid primary key,
  workspace_id uuid not null references public.product_workspaces(workspace_id) on delete cascade,
  agent_id uuid not null references public.agents(agent_id) on delete cascade,
  model text not null,
  tokens_in bigint not null check (tokens_in >= 0),
  tokens_out bigint not null check (tokens_out >= 0),
  cost_usd double precision not null check (cost_usd >= 0),
  latency_ms double precision not null check (latency_ms >= 0),
  created_at timestamptz not null default now()
);
create index if not exists agent_costs_workspace_agent_idx on public.agent_costs(workspace_id, agent_id, created_at);

alter table public.agents enable row level security;
alter table public.agent_evaluations enable row level security;
alter table public.agent_memory enable row level security;
alter table public.agent_costs enable row level security;

create policy agent_workspace_access on public.agents for all using (exists (select 1 from public.workspace_memberships wm where wm.workspace_id=agents.workspace_id and wm.user_id=auth.uid())) with check (exists (select 1 from public.workspace_memberships wm where wm.workspace_id=agents.workspace_id and wm.user_id=auth.uid()));
create policy agent_eval_workspace_access on public.agent_evaluations for all using (exists (select 1 from public.workspace_memberships wm where wm.workspace_id=agent_evaluations.workspace_id and wm.user_id=auth.uid())) with check (exists (select 1 from public.workspace_memberships wm where wm.workspace_id=agent_evaluations.workspace_id and wm.user_id=auth.uid()));
create policy agent_memory_workspace_access on public.agent_memory for all using (exists (select 1 from public.workspace_memberships wm where wm.workspace_id=agent_memory.workspace_id and wm.user_id=auth.uid())) with check (exists (select 1 from public.workspace_memberships wm where wm.workspace_id=agent_memory.workspace_id and wm.user_id=auth.uid()));
create policy agent_cost_workspace_access on public.agent_costs for all using (exists (select 1 from public.workspace_memberships wm where wm.workspace_id=agent_costs.workspace_id and wm.user_id=auth.uid())) with check (exists (select 1 from public.workspace_memberships wm where wm.workspace_id=agent_costs.workspace_id and wm.user_id=auth.uid()));
