'use client';

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import { getSupabaseClient } from '../auth';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const { error: authError } = await getSupabaseClient().auth.signInWithPassword({ email, password });
      if (authError) throw authError;
      router.replace('/workspaces');
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to sign in.');
    } finally {
      setBusy(false);
    }
  }

  return <div className="auth-page">
    <section className="card auth-card">
      <div className="eyebrow">Colab · Secure access</div>
      <h1>Sign in</h1>
      <p>Sign in with your provisioned Colab account to access workspaces and other protected product data.</p>
      {error && <div className="card error" role="alert">{error}</div>}
      <form onSubmit={submit}>
        <label>Email<input required type="email" autoComplete="email" value={email} onChange={event => setEmail(event.target.value)} /></label>
        <label>Password<input required type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} /></label>
        <button className="button" type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
      <p className="muted">Your Colab role is assigned server-side. If authentication succeeds but access is denied, ask an administrator to provision the appropriate Colab role in your Supabase user metadata.</p>
    </section>
  </div>;
}
