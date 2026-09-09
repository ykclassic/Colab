'use client';

import { useState } from 'react';

const sampleResults = (agentId: string, workspaceId: string) => [
  { case_id: crypto.randomUUID(), agent_id: agentId, workspace_id: workspaceId, score: .92, correctness: .95, evidence_quality: .9, latency_ms: 320, tokens_in: 1200, tokens_out: 450, cost_usd: .012, passed: true, rationale: 'Evidence-backed answer' },
  { case_id: crypto.randomUUID(), agent_id: agentId, workspace_id: workspaceId, score: .76, correctness: .8, evidence_quality: .7, latency_ms: 510, tokens_in: 900, tokens_out: 380, cost_usd: .009, passed: true, rationale: 'Acceptable answer' },
];

export default function AgentPlatformPage() {
  const [workspace, setWorkspace] = useState('');
  const [agent, setAgent] = useState('');
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function post(path: string, body: unknown) {
    setBusy(true); setError('');
    try { const response = await fetch(`/api/agents/${path}`, { method: 'POST', headers: {'content-type':'application/json'}, body: JSON.stringify(body) }); const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'Request failed'); setResult(data); }
    catch (e) { setError(e instanceof Error ? e.message : 'Request failed'); } finally { setBusy(false); }
  }

  async function register() {
    await post('registry', { workspace_id: workspace, name: agent || 'research-agent', role: 'research', code_revision: 'main', model: 'configured-model', tools: ['research_search', 'quant_sandbox'] });
  }

  const candidateA = crypto.randomUUID(); const candidateB = crypto.randomUUID();
  return <main><div className="page-head"><div><p className="eyebrow">PHASE 19</p><h1>Agent Platform</h1><p>Register agents, evaluate quality, inspect historical performance, arbitrate competing answers with evidence, manage memory and measure cost.</p></div></div>
    <section className="card"><h2>Agent registry</h2><div className="grid grid-3"><label>Workspace ID<input value={workspace} onChange={e=>setWorkspace(e.target.value)} placeholder="Required" /></label><label>Agent name<input value={agent} onChange={e=>setAgent(e.target.value)} placeholder="Research agent" /></label><div className="actions"><button className="button" disabled={busy || !workspace} onClick={register}>Register agent</button></div></div></section>
    <section className="card"><h2>Evaluation & performance</h2><p className="muted">Evaluation combines correctness, evidence quality, latency, pass rate and cost. Historical performance exposes score trend rather than a single snapshot.</p><button className="button" disabled={busy || !workspace || !agent} onClick={()=>post('evaluate',{workspace_id:workspace,agent_id:agent,results:sampleResults(agent,workspace)})}>Run evaluation</button></section>
    <section className="card"><h2>Evidence-based arbitration</h2><p className="muted">Confidence alone is not sufficient: weakly evidenced answers are explicitly penalized.</p><button className="button" disabled={busy || !workspace} onClick={()=>post('arbitrate',{workspace_id:workspace,candidates:[{agent_id:candidateA,answer:'Candidate A',confidence:.98,evidence:[]},{agent_id:candidateB,answer:'Candidate B',confidence:.82,evidence:[{source_id:'approved-source',claim:'Supporting claim',strength:.95}]}]})}>Arbitrate answers</button></section>
    <section className="card"><h2>Agent memory & cost analytics</h2><div className="actions"><button className="button" disabled={busy || !workspace} onClick={()=>post('memory/search',{workspace_id:workspace,query:'research strategy',limit:10,memories:[]})}>Search memory</button><button className="button" disabled={busy || !workspace || !agent} onClick={()=>post('costs',{workspace_id:workspace,agent_id:agent,records:[]})}>Cost analytics</button></div><p className="muted">Memory is workspace-scoped, confidence-aware and expiry-aware. Cost analytics reports token usage, latency and cost per 1K tokens.</p></section>
    {error && <p className="notice" role="alert">{error}</p>}{result && <section className="card"><h2>Result</h2><pre style={{overflow:'auto'}}>{JSON.stringify(result,null,2)}</pre></section>}
  </main>;
}
