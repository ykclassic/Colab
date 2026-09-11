'use client';

import Link from 'next/link';
import {FormEvent, useEffect, useState} from 'react';
import {archiveWorkspace, createWorkspace, deleteWorkspace, getAuthMe, getWorkspaces, restoreWorkspace, updateWorkspace, Workspace} from '../lib';

const emptyForm = {name: '', product_goal: '', priority: 100};

type Principal = { user_id: string; role: string; email: string | null };

export default function Workspaces() {
  const [items, setItems] = useState<Workspace[]>([]);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [editing, setEditing] = useState<Workspace | null>(null);
  const [busy, setBusy] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [checkingAuth, setCheckingAuth] = useState(true);

  async function refresh() {
    try { setItems(await getWorkspaces(includeArchived)); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to load workspaces.'); }
  }

  useEffect(() => {
    void (async () => {
      try {
        const me = await getAuthMe();
        setPrincipal(me);
        setError('');
      } catch (err) {
        setPrincipal(null);
        setError(err instanceof Error ? err.message : 'Authentication required.');
      } finally {
        setCheckingAuth(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (principal) void refresh();
  }, [includeArchived, principal]);

  function openCreate() { setEditing(null); setForm(emptyForm); setMessage(''); setError(''); }
  function openEdit(workspace: Workspace) {
    setEditing(workspace);
    setForm({name: workspace.name, product_goal: workspace.product_goal, priority: workspace.priority});
    setMessage(''); setError('');
    window.scrollTo({top: 0, behavior: 'smooth'});
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const payload = {...form, strategies: editing?.strategies ?? []};
      if (editing) await updateWorkspace(editing.workspace_id, editing.version, payload);
      else await createWorkspace(payload, crypto.randomUUID());
      setMessage(editing ? 'Workspace updated.' : 'Workspace created.');
      setEditing(null); setForm(emptyForm); await refresh();
    } catch (err) { setError(err instanceof Error ? err.message : 'Workspace operation failed.'); }
    finally { setBusy(false); }
  }

  async function archive(workspace: Workspace) {
    if (!window.confirm(`Archive “${workspace.name}”? It will remain recoverable.`)) return;
    setBusyId(workspace.workspace_id); setError('');
    try { await archiveWorkspace(workspace.workspace_id, workspace.version); setMessage('Workspace archived.'); await refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to archive workspace.'); }
    finally { setBusyId(null); }
  }

  async function restore(workspace: Workspace) {
    setBusyId(workspace.workspace_id); setError('');
    try { await restoreWorkspace(workspace.workspace_id, workspace.version); setMessage('Workspace restored.'); await refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to restore workspace.'); }
    finally { setBusyId(null); }
  }

  async function remove(workspace: Workspace) {
    if (!window.confirm(`Permanently delete “${workspace.name}”? This cannot be undone.`)) return;
    setBusyId(workspace.workspace_id); setError('');
    try { await deleteWorkspace(workspace.workspace_id, workspace.version); setMessage('Workspace permanently deleted.'); await refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to delete workspace.'); }
    finally { setBusyId(null); }
  }

  if (checkingAuth) {
    return <section className="card"><div className="eyebrow">Secure workspace access</div><h1>Checking authentication…</h1><p className="muted">Verifying your Colab session before loading workspace data.</p></section>;
  }

  if (!principal) {
    return <>
      <header className="page-head"><div><div className="eyebrow">Portfolio</div><h1>Workspaces</h1><p>Workspace data is protected by the production tenant boundary.</p></div></header>
      <section className="card auth-card">
        <div className="eyebrow">Authentication required</div>
        <h2>Sign in to manage workspaces</h2>
        <p>Your browser does not currently have a valid Colab session. The workspace API correctly rejected the unauthenticated request.</p>
        <Link className="button" href="/login">Sign in</Link>
        {error && <p className="muted">API response: {error}</p>}
      </section>
    </>;
  }

  return <>
    <header className="page-head">
      <div><div className="eyebrow">Portfolio</div><h1>Workspaces</h1><p>Create, edit, archive and restore product-development contexts without touching the backend.</p></div>
      <button className="button" onClick={openCreate}>+ New workspace</button>
    </header>

    {(message || error) && <div className={`card ${error ? 'error' : ''}`} role="status">{error || message}</div>}

    <section className="card">
      <form onSubmit={submit} className="grid grid-2">
        <div><div className="eyebrow">{editing ? 'Edit workspace' : 'Create workspace'}</div><h2>{editing ? editing.name : 'New workspace'}</h2>
          <label>Name<input required maxLength={200} value={form.name} onChange={e=>setForm({...form,name:e.target.value})} placeholder="Workspace name" /></label>
          <label>Product goal<textarea required maxLength={10000} value={form.product_goal} onChange={e=>setForm({...form,product_goal:e.target.value})} placeholder="What are you trying to build or validate?" /></label>
          <label>Priority<input type="number" min={0} max={1000} value={form.priority} onChange={e=>setForm({...form,priority:Number(e.target.value)})} /></label>
          <div className="actions"><button className="button" type="submit" disabled={busy}>{busy ? (editing ? 'Saving…' : 'Creating…') : (editing ? 'Save changes' : 'Create workspace')}</button>{editing && <button className="button secondary" type="button" onClick={openCreate} disabled={busy}>Cancel</button>}</div>
        </div>
        <div className="panel"><strong>Safe workspace lifecycle</strong><p>Create requests are idempotent, edits use optimistic version checks, and normal removal is archival rather than destructive.</p><p>Permanent deletion is only available after archival and requires explicit confirmation.</p></div>
      </form>
    </section>

    <div className="page-head"><div><h2>Registered workspaces</h2><p>{items.length} {includeArchived ? 'workspace records' : 'active workspaces'}</p></div><label className="toggle"><input type="checkbox" checked={includeArchived} onChange={e=>setIncludeArchived(e.target.checked)} /> Show archived</label></div>

    <div className="grid grid-2">
      {items.map(w=><article className="card" key={w.workspace_id}>
        <div className="page-head"><div><h2>{w.name}</h2><p>{w.product_goal}</p></div><span className="pill">{w.status}</span></div>
        <div className="label">Priority {w.priority} · {w.strategies.length} strategies · Version {w.version}</div>
        <div className="actions">
          {w.status === 'archived' ? <><button className="button secondary" disabled={busyId===w.workspace_id} onClick={()=>void restore(w)}>{busyId===w.workspace_id?'Restoring…':'Restore'}</button><button className="button danger" disabled={busyId===w.workspace_id} onClick={()=>void remove(w)}>Delete permanently</button></> : <><button className="button secondary" onClick={()=>openEdit(w)}>Edit</button><button className="button secondary" disabled={busyId===w.workspace_id} onClick={()=>void archive(w)}>{busyId===w.workspace_id?'Archiving…':'Archive'}</button></>}
        </div>
      </article>)}
      {!items.length && <div className="card empty">No workspaces are currently registered.</div>}
    </div>
  </>;
}
