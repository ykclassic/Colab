'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const links = [
  ['Dashboard', '/'],
  ['Workflows', '/workflows'],
  ['Workspaces', '/workspaces'],
  ['Research', '/research'],
  ['Quantitative Research', '/quant/overview'],
  ['Strategy Research', '/quant/strategy-lab'],
  ['Backtesting & Validation', '/quant/backtesting'],
  ['Performance Analytics', '/quant/performance'],
  ['Risk & Portfolio', '/quant/risk'],
  ['Data Explorer', '/quant/data'],
  ['Live Trading', '/quant/live'],
  ['Research Reports', '/quant/reports'],
  ['Artifacts', '/artifacts'],
  ['Operations', '/operations'],
  ['Governance', '/governance'],
  ['Release Governance', '/governance/release'],
];

export function Nav() {
  const pathname = usePathname();
  return (
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">C</span><div><strong>COLAB</strong><small>Command Center</small></div></div>
      <nav>{links.map(([label, href]) => <Link className={pathname === href ? 'active' : ''} href={href} key={href}>{label}</Link>)}</nav>
      <div className="sidebar-foot"><span className="status-dot" /> Platform online<br /><small>Phase 11 · production validation & release governance</small></div>
    </aside>
  );
}
