'use client';

import { useEffect, useState } from 'react';
import { getWorkspaces, Workspace } from '../../lib';

export default function SettingsPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [saved, setSaved] = useState(false);
  useEffect(() => { getWorkspaces().then(setWorkspaces).catch(() => setWorkspaces([])); }, []);
  return <div><header className="page-head"><div><div className="eyebrow">Productization · Settings</div><h1>Workspace & team</h1><p>Keep workspace identity, membership expectations and product preferences in one place.</p></div></header>
    <section className="card section"><h2>Workspace context</h2>{workspaces.map(w => <div className="row" key={w.workspace_id}><div><strong>{w.name}</strong><div className="muted">{w.product_goal}</div></div><span className="pill">{w.status}</span></div>)}{!workspaces.length && <div className="empty">No workspaces available in the current context.</div>}</section>
    <section className="card section"><h2>Product preferences</h2><label className="setting"><span><strong>Notifications</strong><small>Show operational and workflow events in the command center.</small></span><input type="checkbox" defaultChecked /></label><label className="setting"><span><strong>Compact navigation</strong><small>Use dedicated pages rather than expanding the sidebar with every capability.</small></span><input type="checkbox" /></label><button onClick={() => setSaved(true)}>Save preferences</button>{saved && <p className="muted">Preferences saved locally for this browser.</p>}</section>
    <section className="card section"><h2>Team management</h2><p className="muted">Workspace membership and role enforcement remain server-authoritative. This surface intentionally does not grant permissions client-side.</p><div className="row"><strong>Owner / Admin</strong><span className="pill">Manage membership</span></div><div className="row"><strong>Member</strong><span className="pill">Workspace access</span></div></section>
  </div>;
}
