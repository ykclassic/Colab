# ruff: noqa: I001
"""Production workload handlers kept outside the HTTP request lifecycle."""
from __future__ import annotations
from hashlib import sha256
from typing import Any, cast
from uuid import UUID

def research_ingestion(payload:dict[str,Any],progress:Any)->dict[str,Any]:
 from .research_platform import ExtractionRecord
 from .research_platform_api import ResearchPlatformServices
 services=ResearchPlatformServices(database_dsn=payload.get("database_dsn"),production=bool(payload.get("production",False))); progress(10,"Extracting source content"); text,extractor=services.extractor.extract(payload["content"].encode(),payload.get("media_type","text/plain"),payload.get("filename")); progress(35,"Chunking and embedding research"); document=services.engine.ingest_text(title=payload["title"],text=text,uri=payload["uri"],workspace_id=UUID(payload["workspace_id"]),source_type="research-platform"); services.documents[document.document_id]=UUID(payload["dataset_id"]); chunks=services.engine.store.list_chunks(document.document_id)
 if services.store is not None:
  for chunk in chunks:services.store.save_chunk(chunk_id=chunk.chunk_id,dataset_id=UUID(payload["dataset_id"]),document_id=document.document_id,ordinal=chunk.ordinal,text=chunk.text,embedding=services.embedder.embed(chunk.text),content_hash=chunk.content_hash)
 extraction=ExtractionRecord(dataset_id=UUID(payload["dataset_id"]),media_type=payload.get("media_type","text/plain"),filename=payload.get("filename"),extractor=extractor,extracted_text_hash=sha256(text.encode()).hexdigest(),character_count=len(text));
 if services.store is not None:services.store.save_extraction(extraction.model_dump())
 progress(95,"Research artifact ready"); return {"document_id":str(document.document_id),"dataset_id":payload["dataset_id"],"extraction":extraction.model_dump(mode="json"),"chunk_count":len(chunks)}

def report_generation(payload:dict[str,Any],progress:Any)->dict[str,Any]:
 from .research_platform import RetrievalCandidate, build_report,citation_id_for,rerank,validate_citations
 from .research_platform_api import ResearchPlatformServices
 services=ResearchPlatformServices(database_dsn=payload.get("database_dsn"),production=bool(payload.get("production",False))); progress(15,"Retrieving cited evidence"); query=payload["query"]; limit=int(payload.get("limit",10)); candidate_limit=int(payload.get("candidate_limit",40)); vector=services.embedder.embed(query)
 hits=services.store.hybrid_search(workspace_id=UUID(payload["workspace_id"]),query=query,embedding=vector,limit=candidate_limit,candidate_limit=candidate_limit) if services.store else services.engine.search(query,limit=candidate_limit,workspace_id=UUID(payload["workspace_id"])); ranked=rerank(query,cast(list[RetrievalCandidate],hits),limit); citations=[]; evidence={}
 for h in ranked:
  cid=citation_id_for(h.source_id,h.chunk_id); citations.append({"citation_id":cid,"chunk_id":str(h.chunk_id),"document_id":str(h.document_id),"dataset_id":None,"title":h.title,"uri":h.uri,"quote":" ".join(h.text.split())[:1000]}); evidence[cid]=h.text
 progress(60,"Validating citations"); validations=validate_citations(citations,evidence)
 if not all(x.valid for x in validations):raise ValueError("citation validation failed")
 report=build_report(workspace_id=UUID(payload["workspace_id"]),query=query,answer=payload["answer"],citations=citations,evidence=evidence,dataset_ids=[],retrieval_config={"limit":limit,"candidate_limit":candidate_limit,"reranker":"deterministic-overlap-v1","hybrid":services.store is not None},provider={"name":services.embedder.name,"model":services.embedder.model,"dimensions":services.embedder.dimensions}); progress(95,"Report artifact ready"); return report.model_dump(mode="json")
