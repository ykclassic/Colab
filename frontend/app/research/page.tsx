"use client";

import { FormEvent, useEffect, useState } from "react";

type DocumentRecord = {
  document_id: string;
  title: string;
  text: string;
  version: number;
  content_hash: string;
  created_at: string;
};

type SearchHit = {
  score: number;
  document: DocumentRecord;
  source: { title: string; uri: string; publisher?: string | null };
  chunk: { chunk_id: string; ordinal: number; text: string };
};

type Synthesis = {
  query: string;
  answer: string;
  citations: Array<{
    citation_id: string;
    title: string;
    uri: string;
    locator: string;
    quote: string;
    relevance: number;
  }>;
};

export default function Research() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [title, setTitle] = useState("");
  const [uri, setUri] = useState("");
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [synthesis, setSynthesis] = useState<Synthesis | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function loadDocuments() {
    const response = await fetch("/api/research/documents", { cache: "no-store" });
    if (response.ok) setDocuments(await response.json());
  }

  useEffect(() => {
    void loadDocuments();
  }, []);

  async function ingest(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch("/api/research/documents", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title, uri, text }),
      });
      if (!response.ok) throw new Error(await response.text());
      setTitle(""); setUri(""); setText("");
      setMessage("Document indexed with provenance and embeddings.");
      await loadDocuments();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Document ingestion failed.");
    } finally { setBusy(false); }
  }

  async function research(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setMessage("");
    try {
      const payload = JSON.stringify({ query, limit: 8 });
      const [searchResponse, synthesisResponse] = await Promise.all([
        fetch("/api/research/search", { method: "POST", headers: { "content-type": "application/json" }, body: payload }),
        fetch("/api/research/synthesize", { method: "POST", headers: { "content-type": "application/json" }, body: payload }),
      ]);
      if (!searchResponse.ok || !synthesisResponse.ok) throw new Error("Research request failed.");
      setHits(await searchResponse.json());
      setSynthesis(await synthesisResponse.json());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Research failed.");
    } finally { setBusy(false); }
  }

  return (
    <>
      <header className="page-head">
        <div>
          <div className="eyebrow">Knowledge &amp; Research Intelligence · Phase 8</div>
          <h1>Research</h1>
          <p>Ingest evidence, retrieve it semantically, preserve provenance, and produce citation-grounded research synthesis.</p>
        </div>
      </header>

      {message && <div className="notice section">{message}</div>}

      <div className="grid grid-2">
        <section className="card">
          <h2>Document ingestion</h2>
          <p className="muted">Every document receives a content checksum, immutable source metadata, chunks and embeddings.</p>
          <form onSubmit={ingest}>
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Document title" required />
            <input value={uri} onChange={(e) => setUri(e.target.value)} placeholder="Source URI / reference" required />
            <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste document text or research notes…" rows={9} required />
            <button disabled={busy}>{busy ? "Working…" : "Index document"}</button>
          </form>
        </section>

        <section className="card">
          <h2>Research query</h2>
          <p className="muted">Vector search ranks evidence by cosine similarity. Synthesis retains the exact source chunks used.</p>
          <form onSubmit={research}>
            <textarea value={query} onChange={(e) => setQuery(e.target.value)} placeholder="What do you want to investigate?" rows={4} required />
            <button disabled={busy}>{busy ? "Researching…" : "Search & synthesize"}</button>
          </form>
          {synthesis && <div className="section"><div className="eyebrow">Evidence-grounded synthesis</div><pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", lineHeight: 1.6 }}>{synthesis.answer}</pre></div>}
        </section>
      </div>

      <section className="card section">
        <div className="page-head"><div><h2>Evidence</h2><p className="muted">{hits.length} ranked evidence chunks</p></div></div>
        {hits.length === 0 ? <p className="muted">Run a research query to inspect ranked evidence.</p> : hits.map((hit) => (
          <article key={hit.chunk.chunk_id} className="section" style={{ borderTop: "1px solid var(--border)", paddingTop: 16 }}>
            <div className="eyebrow">Score {hit.score.toFixed(3)} · Chunk {hit.chunk.ordinal + 1}</div>
            <h3>{hit.source.title}</h3>
            <p>{hit.chunk.text}</p>
            <a href={hit.source.uri} target="_blank" rel="noreferrer">{hit.source.uri}</a>
          </article>
        ))}
      </section>

      <section className="card section">
        <h2>Knowledge base</h2>
        <div className="grid grid-2">
          {documents.map((document) => (
            <article key={document.document_id}>
              <div className="eyebrow">v{document.version}</div>
              <h3>{document.title}</h3>
              <p className="muted">{document.text.slice(0, 220)}{document.text.length > 220 ? "…" : ""}</p>
              <code>{document.content_hash.slice(0, 16)}…</code>
            </article>
          ))}
        </div>
        {documents.length === 0 && <p className="muted">No indexed documents yet.</p>}
      </section>

      {synthesis && synthesis.citations.length > 0 && <section className="card section">
        <h2>Citation ledger</h2>
        {synthesis.citations.map((citation) => (
          <article key={citation.citation_id} className="section" style={{ borderTop: "1px solid var(--border)", paddingTop: 12 }}>
            <strong>{citation.citation_id}</strong> · {citation.title} · relevance {citation.relevance.toFixed(3)}
            <p className="muted">{citation.locator}: “{citation.quote}”</p>
            <a href={citation.uri} target="_blank" rel="noreferrer">Open source</a>
          </article>
        ))}
      </section>}
    </>
  );
}
