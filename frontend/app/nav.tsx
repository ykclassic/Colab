'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const links = [
  ['Dashboard', '/'],
  ['Workflows', '/workflows'],
  ['Workspaces', '/workspaces'],
  ['Research', '/research'],
  ['Quant Lab', '/quant'],
  ['Artifacts', '/artifacts'],
  ['Operations', '/operations'],
  ['Governance', '/governance'],
];

export function Nav() {
  const pathname = usePathname();
  return (
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">C</span><div><strong>COLAB</strong><small>Command Center</small></div></div>
      <nav>{links.map(([label, href]) => <Link className={pathname === href ? 'active' : ''} href={href} key={href}>{label}</Link>)}</nav>
      <div className="sidebar-foot"><span className="status-dot" /> Platform online<br /><small>Phase 10 · research control plane</small></div>
    </aside>
  );
}
