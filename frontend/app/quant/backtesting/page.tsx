"use client";

import { useMemo, useState } from "react";

const checks = [
  ["Look-ahead leakage", "Signals are evaluated at t and fills begin at t+1."],
  ["Survivorship bias", "Point-in-time universe policy must include delisted constituents."],
  ["Selection bias", "Parameter selection is restricted to training windows."],
  ["Timestamp/data leakage", "Timezone-aware, strictly ordered, duplicate-free timestamps."],
  ["Parameter / feature leakage", "Features are tied to the exact dataset checksum and causal windows."],
  ["Corporate actions", "Split/dividend adjustment policy is an explicit validation input."],
  ["Missing / duplicate / stale data", "Gap and stale-data policy must be recorded before acceptance."],
  ["Spread / slippage", "Positive slippage and non-negative commissions are required."],
  ["Unrealistic fills", "Execution policy is explicitly next-bar-open rather than hindsight close fills."],
];

export default function BacktestingPage() {
  const [showMethod, setShowMethod] = useState(false);
  const passed = useMemo(() => checks.length, []);

  return (
    <main>
      <div className="page-head">
        <div>
          <p className="eyebrow">QUANTITATIVE RESEARCH · PHASE 21E</p>
          <h1>Backtesting &amp; Scientific Validation</h1>
          <p>Dataset → Strategy → Experiment → Backtest → Walk-forward/OOS → Risk → Stress → Monte Carlo → Robustness → Persistence.</p>
        </div>
      </div>

      <div className="card">
        <div style={{display:"flex",justifyContent:"space-between",gap:16,alignItems:"center"}}>
          <div><h2>Research acceptance gate</h2><p className="muted">A quantitative result is research evidence only when the causal data, execution and validation assumptions are explicit.</p></div>
          <strong>{passed}/9 controls defined</strong>
        </div>
        <button className="button" onClick={() => setShowMethod(!showMethod)}>{showMethod ? "Hide controls" : "Review controls"}</button>
      </div>

      {showMethod && <div className="card">
        <h2>Scientific controls</h2>
        <div style={{display:"grid",gap:10}}>
          {checks.map(([title, detail]) => <div key={title} className="card" style={{margin:0}}><strong>✓ {title}</strong><p className="muted">{detail}</p></div>)}
        </div>
      </div>}

      <div className="card">
        <h2>Vertical slice status</h2>
        <p className="muted">The backend now treats scientific validation, reproducibility hashes, walk-forward/OOS separation, risk analytics, stress testing, Monte Carlo and robustness as one auditable research run. Results remain research-only and are not execution authority.</p>
        <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(180px,1fr))",gap:10}}>
          {["Dataset","Strategy","Experiment","Backtest","Walk-forward / OOS","Risk","Stress","Monte Carlo","Robustness","Persistence"].map(stage => <div key={stage} className="card" style={{margin:0}}><strong>✓</strong><p>{stage}</p></div>)}
        </div>
      </div>
    </main>
  );
}
