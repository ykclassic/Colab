import Link from 'next/link';

const areas = [
  ['Quantitative Strategy Lab', '/quant/strategy-lab', 'Design and compare parameterized research strategies.'],
  ['Backtesting & Validation', '/quant/backtesting', 'Run historical simulations with explicit costs and validation controls.'],
  ['Performance Analytics', '/quant/performance', 'Inspect return, volatility, Sharpe, drawdown and trade statistics.'],
  ['Risk & Portfolio', '/quant/risk', 'Research exposure, concentration and portfolio-level risk.'],
  ['Data Explorer', '/quant/data', 'Inspect dataset provenance, chronology, features and checksums.'],
  ['Live Trading', '/quant/live', 'Future research-to-execution boundary; trading is intentionally not enabled here.'],
  ['Research Reports', '/quant/reports', 'Future publication and experiment-reporting workspace.'],
];

export default function QuantitativeResearchOverview() {
  return <main><div className="page-head"><div><p className="eyebrow">PHASE 10</p><h1>Quantitative Research Overview</h1><p>Research-only workspace for datasets, features, strategies, validation and experiment evidence.</p></div></div><div className="grid grid-2">{areas.map(([title, href, description]) => <Link className="card link" href={href} key={href}><h2>{title}</h2><p className="muted">{description}</p></Link>)}</div><section className="section"><div className="notice">Research results do not authorize execution. Existing workflow governance and approval controls remain authoritative.</div></section></main>;
}
