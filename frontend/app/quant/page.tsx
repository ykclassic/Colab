'use client';

import { useState } from 'react';

const sampleBars = Array.from({ length: 60 }, (_, i) => {
  const close = 100 + i * 0.25 + (i % 9 === 0 ? 2 : 0);
  return {
    timestamp: new Date(Date.UTC(2025, 0, 1 + i)).toISOString(),
    symbol: 'RESEARCH', open: close - 0.1, high: close + 0.5,
    low: close - 0.5, close, volume: 1000 + i * 10,
  };
});

export default function QuantLabPage() {
  const [fast, setFast] = useState(5);
  const [slow, setSlow] = useState(20);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);

  async function runBacktest() {
    setBusy(true);
    try {
      const response = await fetch('/api/quant/backtest', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ symbol: 'RESEARCH', bars: sampleBars, fast_window: fast, slow_window: slow }),
      });
      setResult(await response.json());
    } finally { setBusy(false); }
  }

  const metrics = (result?.result as { metrics?: Record<string, number> } | undefined)?.metrics;
  return (
    <main className="page-shell">
      <div className="page-heading"><div><p className="eyebrow">PHASE 10</p><h1>Quantitative Research Lab</h1><p>Feature engineering, backtesting, parameter experiments and walk-forward/OOS research in an isolated research plane.</p></div></div>
      <section className="card">
        <h2>Moving-average experiment</h2>
        <div className="form-grid">
          <label>Fast window<input type="number" min={2} max={250} value={fast} onChange={e => setFast(Number(e.target.value))} /></label>
          <label>Slow window<input type="number" min={3} max={500} value={slow} onChange={e => setSlow(Number(e.target.value))} /></label>
        </div>
        <button disabled={busy || fast >= slow} onClick={runBacktest}>{busy ? 'Running…' : 'Run backtest'}</button>
      </section>
      {metrics && <section className="card"><h2>Backtest results</h2><div className="metric-grid">
        {Object.entries(metrics).map(([key, value]) => <div key={key}><small>{key.replaceAll('_', ' ')}</small><strong>{typeof value === 'number' ? value.toFixed(4) : String(value)}</strong></div>)}
      </div></section>}
      {result && <section className="card"><h2>Experiment evidence</h2><p>Dataset checksum: <code>{String(result.dataset_checksum)}</code></p><p>Results are research artifacts only; this page does not execute trades.</p></section>}
    </main>
  );
}
