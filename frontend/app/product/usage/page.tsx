'use client';

import { useEffect, useState } from 'react';
import { getMetrics, Metrics } from '../../lib';

export default function UsagePage() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  useEffect(() => { getMetrics().then(setMetrics).catch(() => setMetrics(null)); }, []);
  const completed = metrics?.succeeded ?? 0;
  const failed = metrics?.failed ?? 0;
  const total = completed + failed + (metrics?.running ?? 0) + (metrics?.pending ?? 0);
  return <div><header className="page-head"><div><div className="eyebrow">Productization · Usage</div><h1>Usage & cost</h1><p>Operational consumption for the current platform workspace context.</p></div></header>
    <div className="grid grid-4 section">{[['Total jobs', total],['Successful',completed],['Failed',failed],['Retries',metrics?.retries ?? '—']].map(([a,b])=><div className="card" key={a}><div className="label">{a}</div><div className="metric">{b}</div></div>)}</div>
    <section className="card section"><h2>Cost model</h2><p className="muted">The product surface is ready for provider billing telemetry. Costs should be populated from recorded agent token/call telemetry rather than inferred from job counts.</p><div className="grid grid-3"><div className="card nested"><div className="label">Agent calls</div><div className="metric">Tracked in Agent Platform</div></div><div className="card nested"><div className="label">Token spend</div><div className="metric">Tracked per evaluation</div></div><div className="card nested"><div className="label">Execution spend</div><div className="metric">Workflow dependent</div></div></div></section>
  </div>;
}
