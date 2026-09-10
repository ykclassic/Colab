'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { getEvents, getMetrics, getTools, getWorkspaces, Metrics, Workspace, Event, Tool, createWorkspace } from '../lib';
import { planWorkflow, WorkflowPlan } from './workflow';

export default function ProductCommandCenter() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [command, setCommand] = useState('');
  const [plan, setPlan] = useState<WorkflowPlan | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([getMetrics(), getWorkspaces(), getEvents(), getTools()]).then(([m, w, e, t]) => {
      setMetrics(m); setWorkspaces(w); setEvents(e); setTools(t);
    }).catch(() => setMessage('Some live platform data is unavailable.'));
  }, []);

  function previewCommand() {
    const goal = command.trim();
    if (!goal) return;
    setMessage('');
    setPlan(planWorkflow(goal));
  }

  async function startWorkflow() {
    if (!plan || !command.trim()) return;
    setBusy(true);
    setMessage('Creating workspace and routing the goal…');
    try {
      const workspace = await createWorkspace(
        { name: `${plan.name} — ${command.trim().slice(0, 60)}`, product_goal: command.trim(), priority: 100 },
        `command-center:${crypto.randomUUID()}`,
      );
      window.location.href = `/workspaces?workspace=${workspace.workspace_id}`;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to start workflow.');
      setBusy(false);
    }
  }

  return <div>
    <header className="page-head"><div><div className="eyebrow">Phase 21I · Product Command Center</div><h1>Turn a goal into a workflow.</h1><p>Describe the outcome you want. The Command Center selects an appropriate workflow, shows the stages, then creates the workspace context for execution.</p></div><Link className="button" href="/workspaces">Manage workspaces</Link></header>

    <section className="command-bar card section">
      <label htmlFor="command"><strong>What are you trying to accomplish?</strong></label>
      <div className="command-row"><input id="command" value={command} onChange={e => setCommand(e.target.value)} onKeyDown={e => e.key === 'Enter' && previewCommand()} placeholder="Example: investigate whether momentum survives transaction costs" /><button onClick={previewCommand}>Plan workflow</button></div>
      <p className="muted">The planner is deterministic and explainable; it does not silently execute trades or bypass governance.</p>
      {plan && <div className="card nested section">
        <div className="eyebrow">Recommended workflow</div><h2>{plan.name}</h2><p>{plan.description}</p>
        <div className="timeline">{plan.stages.map((stage, index) => <div className="stage" key={stage}><b>{String(index + 1).padStart(2, '0')}</b><span>{stage}</span></div>)}</div>
        <div className="command-row section"><button onClick={startWorkflow} disabled={busy}>{busy ? 'Starting…' : 'Start workflow'}</button><Link className="button" href={plan.destination}>Inspect first stage</Link></div>
      </div>}
      {message && <p role="status" className="muted">{message}</p>}
    </section>

    <div className="grid grid-4 section">{[
      ['Workspaces', workspaces.length], ['Running', metrics?.running ?? '—'], ['Tools', tools.length], ['Failed', metrics?.failed ?? '—']
    ].map(([label, value]) => <div className="card" key={label}><div className="label">{label}</div><div className="metric">{value}</div><div className="muted">workspace-aware platform state</div></div>)}</div>

    <section className="card section"><div className="section-head"><div><h2>End-to-end product path</h2><p className="muted">The user-facing product is organized as a connected delivery journey rather than isolated backend capabilities.</p></div><Link href="/workflows">View workflow map →</Link></div><div className="timeline">{['Command Center','Research','Quant','Agents','Governance','Artifact / Report'].map((stage, i) => <div className="stage" key={stage}><b>{String(i + 1).padStart(2, '0')}</b><span>{stage}</span></div>)}</div></section>

    <section className="card section"><div className="section-head"><div><h2>Workflow templates</h2><p className="muted">Proven starting points remain available when the user already knows the workflow they need.</p></div><Link href="/workflows">All workflows →</Link></div><div className="grid grid-3">{[
      ['Research → Strategy', 'Research a question, validate evidence, then hand findings to strategy.', '/research'],
      ['Quant Validation', 'Move from dataset to backtest, validation and risk review.', '/quant/overview'],
      ['Governed Release', 'Prepare an artifact for readiness, approval and controlled release.', '/governance/release'],
    ].map(([name, description, href]) => <Link className="card nested" href={href} key={name}><h3>{name}</h3><p className="muted">{description}</p><span>Open template →</span></Link>)}</div></section>

    <div className="grid grid-2 section"><section className="card"><h2>Active workspaces</h2>{workspaces.slice(0, 6).map(w => <Link className="row" href={`/workspaces?workspace=${w.workspace_id}`} key={w.workspace_id}><div><strong>{w.name}</strong><div className="muted">{w.product_goal}</div></div><span className="pill">{w.status}</span></Link>)}{!workspaces.length && <div className="empty">Create a workspace to begin.</div>}</section>
      <section className="card"><h2>Notifications</h2>{events.slice(0, 6).map((e, i) => <div className="row" key={`${e.event_type}-${i}`}><div><strong>{e.event_type}</strong><div className="muted">{e.message}</div></div><span className="pill">{e.level}</span></div>)}{!events.length && <div className="empty">No notifications yet.</div>}</section></div>

    <section className="card section"><div className="section-head"><div><h2>Product surfaces</h2><p className="muted">Dedicated pages keep the interface uncluttered while preserving deep functionality.</p></div></div><div className="link-grid">{[['Agents','/agents'],['Research','/research'],['Quant','/quant/overview'],['Risk & Portfolio','/quant/risk'],['Governance','/governance'],['Artifacts / Reports','/artifacts'],['Usage & Cost','/product/usage'],['Team & Settings','/product/settings']].map(([label, href]) => <Link className="surface-link" href={href} key={href}><strong>{label}</strong><span>Open →</span></Link>)}</div></section>
  </div>;
}
