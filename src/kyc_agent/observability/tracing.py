from contextlib import contextmanager
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from ..config import settings

_initialized = False

def init_tracing():
    global _initialized
    if _initialized:
        return
    if settings.otel_enabled:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        resource = Resource.create({
            "service.name": settings.app_name,
            "service.version": settings.app_version,
            "deployment.environment": settings.environment,
        })
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
    _initialized = True

def get_tracer(name="kyc-agent"):
    init_tracing()
    return trace.get_tracer(name)

@contextmanager
def span(name: str, attributes: dict | None = None):
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as current:
        for key, value in (attributes or {}).items():
            if value is not None and isinstance(value, (str, int, float, bool)):
                current.set_attribute(key, value)
        try:
            yield current
        except Exception as exc:
            current.record_exception(exc)
            current.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
