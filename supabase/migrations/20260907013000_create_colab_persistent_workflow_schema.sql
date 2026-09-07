create extension if not exists pgcrypto;

create table public.workflows (
  workflow_id uuid primary key,
  schema_version text not null default '1.0',
  product_goal text not null,
  product_brief jsonb not null default '{}'::jsonb,
  roadmap jsonb not null default '[]'::jsonb,
  current_stage text not null,
  iteration_count integer not null default 0 check (iteration_count >= 0),
  budgets jsonb not null default '{}'::jsonb,
  final_package jsonb,
  version bigint not null default 1 check (version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.workflow_checkpoints (
  checkpoint_id uuid primary key default gen_random_uuid(),
  workflow_id uuid not null references public.workflows(workflow_id) on delete cascade,
  version bigint not null check (version > 0),
  state jsonb not null,
  created_at timestamptz not null default now(),
  unique (workflow_id, version)
);

create table public.agent_tasks (
  task_id uuid primary key,
  workflow_id uuid not null references public.workflows(workflow_id) on delete cascade,
  role text not null,
  objective text not null,
  stage text not null,
  status text not null default 'pending',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.artifacts (
  artifact_id uuid primary key,
  workflow_id uuid not null references public.workflows(workflow_id) on delete cascade,
  kind text not null,
  version integer not null default 1 check (version > 0),
  producer text not null,
  content jsonb not null,
  created_at timestamptz not null default now(),
  unique (workflow_id, artifact_id, version)
);

create table public.risk_assessments (
  assessment_id uuid primary key,
  workflow_id uuid not null references public.workflows(workflow_id) on delete cascade,
  decision text not null,
  findings jsonb not null default '[]'::jsonb,
  controls jsonb not null default '[]'::jsonb,
  assessor text not null,
  created_at timestamptz not null default now()
);

create table public.workflow_decisions (
  decision_id uuid primary key default gen_random_uuid(),
  workflow_id uuid not null references public.workflows(workflow_id) on delete cascade,
  decision jsonb not null,
  created_at timestamptz not null default now()
);

create table public.workflow_approvals (
  approval_id uuid primary key default gen_random_uuid(),
  workflow_id uuid not null references public.workflows(workflow_id) on delete cascade,
  approval jsonb not null,
  created_at timestamptz not null default now()
);

create table public.audit_events (
  event_id uuid primary key,
  workflow_id uuid not null references public.workflows(workflow_id) on delete cascade,
  event_type text not null,
  stage text not null,
  actor text not null,
  message text not null,
  at timestamptz not null
);

create index workflows_stage_idx on public.workflows(current_stage);
create index workflow_checkpoints_workflow_idx on public.workflow_checkpoints(workflow_id, version desc);
create index agent_tasks_workflow_idx on public.agent_tasks(workflow_id, status);
create index artifacts_workflow_idx on public.artifacts(workflow_id, kind, version desc);
create index risk_assessments_workflow_idx on public.risk_assessments(workflow_id, created_at desc);
create index workflow_decisions_workflow_idx on public.workflow_decisions(workflow_id, created_at desc);
create index workflow_approvals_workflow_idx on public.workflow_approvals(workflow_id, created_at desc);
create index audit_events_workflow_idx on public.audit_events(workflow_id, at desc);

alter table public.workflows enable row level security;
alter table public.workflow_checkpoints enable row level security;
alter table public.agent_tasks enable row level security;
alter table public.artifacts enable row level security;
alter table public.risk_assessments enable row level security;
alter table public.workflow_decisions enable row level security;
alter table public.workflow_approvals enable row level security;
alter table public.audit_events enable row level security;

create or replace function public.set_updated_at() returns trigger
language plpgsql security invoker set search_path = public
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger workflows_set_updated_at before update on public.workflows
for each row execute function public.set_updated_at();
create trigger agent_tasks_set_updated_at before update on public.agent_tasks
for each row execute function public.set_updated_at();
