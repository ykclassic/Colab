'use client';

import { useEffect, useState } from 'react';

type Version = { version_id: string; name: string; version: string; artifact_digest: string; manifest_hash: string; created_at: string };
type Decision = { decision_id: string; version_id: string; from_stage: string; to_stage: string; approved: boolean; readiness_score: number; reasons: string[] };

export default function ReleaseGovernance() {
  const [versions, setVersions] = useState<Version[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);

  useEffect(() => {
    Promise.all([
      fetch('/api/governance/versions').then((r) => r.json()),
      fetch('/api/governance/decisions').then((r) => r.json()),
    ]).then(([v, d]) => { setVersions(v); setDecisions(d); });
  }, []);

  return (
    <>
      <header className="page-head">
        <div><div className="eyebrow">Phase 11 · Production validation</div><h1>Release Governance</h1><p>Reproducibility, immutable strategy versions, regression gates, promotion controls, and production-readiness scoring.</p></div>
        <span className="pill">Promotion controlled</span>
      </header>
      <div className="grid grid-2">
        <section className="card"><h2>Promotion gates</h2><div className="row"><strong>Candidate</strong><span className="pill">≥ 70</span></div><div className="row"><strong>Staging</strong><span className="pill">≥ 80</span></div><div className="row"><strong>Production</strong><span className="pill">≥ 90</span></div><p className="muted">Production additionally requires operational-readiness and risk gates to pass.</p></section>
        <section className="card"><h2>Reproducibility</h2><div className="metric">Manifest anchored</div><p className="muted">Dataset checksum, feature configuration, strategy parameters, code revision, dependency-lock hash, seed, and environment are bound into a deterministic manifest.</p></section>
      </div>
      <section className="card section"><h2>Registered strategy versions</h2>{versions.length ? versions.map((v) => <div className="row" key={v.version_id}><div><strong>{v.name} v{v.version}</strong><br /><small className="muted">artifact {v.artifact_digest.slice(0, 12)} · manifest {v.manifest_hash.slice(0, 12)}</small></div><span className="pill">immutable</span></div>) : <p className="muted">No strategy versions registered yet.</p>}</section>
      <section className="card section"><h2>Promotion history</h2>{decisions.length ? decisions.map((d) => <div className="row" key={d.decision_id}><div><strong>{d.from_stage} → {d.to_stage}</strong><br /><small className="muted">readiness {d.readiness_score.toFixed(1)}</small></div><span className="pill">{d.approved ? 'approved' : 'blocked'}</span></div>) : <p className="muted">No promotion decisions recorded.</p>}</section>
      <div className="notice section">This control plane validates and authorizes promotion decisions; it does not deploy models or execute trades. Existing human-review and execution boundaries remain in force.</div>
    </>
  );
}
