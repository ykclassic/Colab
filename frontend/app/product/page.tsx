'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { getEvents, getMetrics, getTools, getWorkspaces, Metrics, Workspace, Event, Tool } from '../lib';

const templates = [
  { name: 'Research → Strategy', description: 'Research a question, validate evidence, then hand findings to the strategy workflow.', href: '/research' },
  { name: 'Quant Validation', description: 'Move from dataset to backtest, walk-forward validation and risk review.', href: '/quant/overview' },
  { name: 'Governed Release', description: 'Prepare an artifact for readiness, approval and controlled release governance.', href: '/governance/release' },
];

export default function ProductCommandCenter() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [command, setCommand] = useState('');
  const [message, setMessage] = useState('');

  useEffect(() => {
    Promise.all([getMetrics(), getWorkspaces(), getEvents(), getTools()]).then(([m, w, e, t]) => {
      setMetrics(m); setWorkspaces(w); setEvents(e); setTools(t);
    }).catch(() => setMessage('Some live platform data is unavailable.'));
  }, []);

  function runCommand() {
    const q = command.trim().toLowerCase();
    if (!q) return;
    if (q.includes('research')) window.location.href = '/research';
    else if (q.includes('quant') || q.includes('backtest')) window.location.href = '/quant/overview';
    else if (q.includes('agent')) window.location.href = '/agents';
    else if (q.includes('workflow')) window.location.href = '/workflows';
    else if (q.includes('risk')) window.location.href = '/quant/risk';
    else if (q.includes('govern')) window.location.href = '/governance';
    else setMessage(`Command received: “${command}”. Try research, quant, agents, workflows, risk or governance.`);
  }

  return <div>
    <header className="page-head"><div><div className="eyebrow">Phase 20 · Productization</div><h1>One workspace. One command center.</h1><p>Run research, agent, quant and governance workflows from a workspace-centric product surface.</p></div><Link className="button" href="/workspaces">Manage workspaces</Link></header>

    <section className="command-bar card section"><label htmlFor="command"><strong>Universal command</strong></label><div className="command-row"><input id="command" value={command} onChange={e => setCommand(e.target.value)} onKeyDown={e => e.key === 'Enter' && runCommand()} placeholder="Try: run quant research, show agents, open risk" /><button onClick={runCommand}>Run</button></div>{message && <p className="muted">{message}</p>}</section>

    <div className="grid grid-4 section">{[
      ['Workspaces', workspaces.length], ['Running', metrics?.running ?? '—'], ['Tools', tools.length], ['Failed', metrics?.failed ?? '—']
    ].map(([label, value]) => <div className="card" key={label}><div className="label">{label}</div><div className="metric">{value}</div><div className="muted">workspace-aware platform state</div></div>)}</div>

    <section className="card section"><div className="section-head"><div><h2>Workflow templates</h2><p className="muted">Start with a proven product workflow instead of assembling every step manually.</p></div><Link href="/workflows">All workflows →</Link></div><div className="grid grid-3">{templates.map(t => <Link className="card nested" href={t.href} key={t.name}><h3>{t.name}</h3><p className="muted">{t.description}</p><span>Open template →</span></Link>)}</div></section>

    <div className="grid grid-2 section"><section className="card"><h2>Active workspaces</h2>{workspaces.slice(0, 6).map(w => <Link className="row" href={`/workspaces/${w.workspace_id}`} key={w.workspace_id}><div><strong>{w.name}</strong><div className="muted">{w.product_goal}</div></div><span className="pill">{w.status}</span></Link>)}{!workspaces.length && <div className="empty">Create a workspace to begin.</div>}</section>
      <section className="card"><h2>Notifications</h2>{events.slice(0, 6).map((e, i) => <div className="row" key={`${e.event_type}-${i}`}><div><strong>{e.event_type}</strong><div className="muted">{e.message}</div></div><span className="pill">{e.level}</span></div>)}{!events.length && <div className="empty">No notifications yet.</div>}</section></div>

    <section className="card section"><div className="section-head"><div><h2>Product surfaces</h2><p className="muted">Dedicated pages keep the interface uncluttered while preserving deep functionality.</p></div></div><div className="link-grid">{[['Agents','/agents'],['Research','/research'],['Quant','/quant/overview'],['Risk & Portfolio','/quant/risk'],['Usage & Cost','/product/usage'],['Team & Settings','/product/settings']].map(([label, href]) => <Link className="surface-link" href={href} key={href}><strong>{label}</strong><span>Open →</span></Link>)}</div></section>
  </div>;
}
