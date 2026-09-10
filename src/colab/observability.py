"""Phase 21H observability: tracing, correlation IDs, structured logs and metrics."""
from __future__ import annotations
import contextvars
import json
import logging
import os
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode
try:
 from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
except ImportError: OTLPSpanExporter = None  # type: ignore[assignment,misc]
_correlation_id: contextvars.ContextVar[str|None]=contextvars.ContextVar("correlation_id",default=None)
_job_id: contextvars.ContextVar[str|None]=contextvars.ContextVar("job_id",default=None)
class JsonFormatter(logging.Formatter):
 def format(self,record:logging.LogRecord)->str:
  payload:dict[str,Any]={"timestamp":time.time(),"level":record.levelname,"logger":record.name,"message":record.getMessage(),"correlation_id":correlation_id(),"job_id":_job_id.get()}
  if record.exc_info:payload["exception"]=self.formatException(record.exc_info)
  return json.dumps(payload,separators=(",",":"),default=str)
def configure_logging()->None:
 root=logging.getLogger()
 if not root.handlers:
  handler=logging.StreamHandler(); handler.setFormatter(JsonFormatter()); root.addHandler(handler)
 root.setLevel(os.getenv("COLAB_LOG_LEVEL","INFO").upper())
def configure_telemetry(service_name:str="colab-agent-platform")->None:
 resource=Resource.create({"service.name":service_name,"service.version":os.getenv("COLAB_VERSION","0.8.0")}); provider=TracerProvider(resource=resource); endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
 if endpoint and OTLPSpanExporter is not None:provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
 try:trace.set_tracer_provider(provider)
 except Exception:pass
 try:metrics.set_meter_provider(MeterProvider(resource=resource))
 except Exception:pass
configure_logging(); configure_telemetry(); tracer=trace.get_tracer("colab"); meter=metrics.get_meter("colab")
request_counter=meter.create_counter("colab.http.requests",unit="1",description="HTTP requests"); request_latency=meter.create_histogram("colab.http.duration",unit="ms",description="HTTP request latency"); job_counter=meter.create_counter("colab.jobs.completed",unit="1",description="Completed or failed jobs"); job_latency=meter.create_histogram("colab.jobs.duration",unit="ms",description="Job execution latency"); retry_counter=meter.create_counter("colab.jobs.retries",unit="1",description="Job retries")
def correlation_id()->str:
 value=_correlation_id.get()
 if value is None:value=str(uuid4()); _correlation_id.set(value)
 return value
@contextmanager
def correlation(value:str|None=None)->Iterator[str]:
 token=_correlation_id.set(value or str(uuid4()))
 try:yield _correlation_id.get() or ""
 finally:_correlation_id.reset(token)
@contextmanager
def job_context(job_id:str)->Iterator[None]:
 token=_job_id.set(job_id)
 try:yield
 finally:_job_id.reset(token)
@contextmanager
def span(name:str,*,attributes:dict[str,Any]|None=None)->Iterator[Span]:
 with tracer.start_as_current_span(name) as current:
  current.set_attribute("correlation_id",correlation_id())
  if _job_id.get():current.set_attribute("job.id",_job_id.get() or "")
  for key,value in (attributes or {}).items():
   if value is not None:current.set_attribute(key,str(value) if not isinstance(value,(bool,int,float)) else value)
  try:yield current
  except Exception as exc:current.record_exception(exc); current.set_status(Status(StatusCode.ERROR,str(exc))); raise
def instrument_boundary(name:str):
 def decorator(function:Any)->Any:
  def wrapped(*args:Any,**kwargs:Any)->Any:
   with span(name,attributes={"code.function":getattr(function,"__qualname__",name)}):return function(*args,**kwargs)
  wrapped.__name__=getattr(function,"__name__","wrapped"); wrapped.__doc__=function.__doc__; return wrapped
 return decorator
def observe_job(status:str,duration_ms:float,job_type:str,attempt:int=1)->None:
 job_counter.add(1,{"status":status,"job_type":job_type}); job_latency.record(duration_ms,{"job_type":job_type})
 if attempt>1:retry_counter.add(attempt-1,{"job_type":job_type})
def observe_http(method:str,route:str,status_code:int,duration_ms:float)->None:
 attrs={"method":method,"route":route,"status_code":status_code}; request_counter.add(1,attrs); request_latency.record(duration_ms,attrs)
class MetricsRegistry:
 def __init__(self)->None:self._counters:Counter[str]=Counter()
 def increment(self,key:str,amount:int=1)->None:self._counters[key]+=amount
 def snapshot(self)->dict[str,int]:return dict(self._counters)
registry=MetricsRegistry()
