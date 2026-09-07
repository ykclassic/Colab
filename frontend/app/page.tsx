'use client';

import { useEffect, useState } from 'react';
import { getEvents, getMetrics, getTools, getWorkspaces, Metrics, Workspace, Event, Tool } from './lib';

const stages = ['Intake','Research','Strategy','Risk','Implementation','Validation','Synthesis','Human Review'];
const agents = [['CEO / Project Lead','Direction'],['Quant Researcher','Research'],['Strategy Developer','Strategy'],['Risk Officer','Independent gate'],['Engineer / QA','Build & validation']];

export default function Dashboard() {
  const [metrics,setMetrics]=useState<Metrics|null>(null); const [workspaces,setWorkspaces]=useState<Workspace[]>([]); const [events,setEvents]=useState<Event[]>([]); const [tools,setTools]=useState<Tool[]>([]); const [error,setError]=useState('');
  useEffect(()=>{Promise.all([getMetrics(),getWorkspaces(),getEvents(),getTools()]).then(([m,w,e,t])=>{setMetrics(m);setWorkspaces(w);setEvents(e);setTools(t)}).catch(()=>setError('Backend data is unavailable. Start the FastAPI service and check NEXT_PUBLIC_COLAB_API_URL.'))},[]);
  return <><header className="page-head"><div><div className="eyebrow">Phase 5.5 · Command Center</div><h1>Agentic collaboration, at a glance.</h1><p>One operational view across research, strategy, risk, engineering and governance.</p></div><span className="pill">Foundation → Phase 5 complete</span></header>
    {error&&<div className="notice section">{error}</div>}
    <div className="grid grid-4 section">{[['Active / pending',metrics?metrics.pending+metrics.running:'—'],['Running',metrics?.running??'—'],['Succeeded',metrics?.succeeded??'—'],['Failed',metrics?.failed??'—']].map(([a,b])=><div className="card" key={a}><div className="label">{a}</div><div className="metric">{b}</div><div className="muted">live coordinator state</div></div>)}</div>
    <section className="card section"><h2>Product development lifecycle</h2><div className="timeline">{stages.map((s,i)=><div className="stage" key={s}><b>{String(i+1).padStart(2,'0')}</b><span>{s}</span></div>)}</div></section>
    <section className="card section"><h2>Executive agent team</h2><div className="agent-grid">{agents.map(([name,role])=><div className="agent" key={name}><strong>{name}</strong><span>{role}</span></div>)}</div><p className="muted">The Risk Officer remains visually and operationally independent from strategy. Human review is the final critical-output gate.</p></section>
    <div className="grid grid-2 section"><section className="card"><h2>Workspaces</h2>{workspaces.length?workspaces.slice(0,6).map(w=><div className="row" key={w.workspace_id}><div><strong>{w.name}</strong><div className="muted">{w.product_goal}</div></div><span className="pill">{w.status}</span></div>):<div className="empty">No workspaces yet.</div>}</section><section className="card"><h2>Recent activity</h2>{events.length?events.slice(0,8).map((e,i)=><div className="row" key={`${e.event_type}-${i}`}><div><strong>{e.event_type}</strong><div className="muted">{e.message}</div></div><span className="pill">{e.level}</span></div>):<div className="empty">No operational events yet.</div>}</section></div>
    <section className="card section"><h2>Approved tool surface</h2><p className="muted">{tools.length} registered tools · execution remains outside this product surface.</p></section></>;
}
