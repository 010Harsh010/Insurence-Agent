from prometheus_client import Counter, Histogram, Gauge

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"]
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"]
)

CLAIMS_PROCESSED = Counter(
    "claims_processed_total",
    "Total claims processed",
    ["decision"]
)

CLAIM_PROCESSING_TIME = Histogram(
    "claim_processing_seconds",
    "Time taken to process a claim"
)

ACTIVE_REQUESTS = Gauge(
    "active_requests",
    "Current active requests"
)

DOCUMENTS_PROCESSED = Counter(
    "documents_processed_total",
    "Documents processed",
    ["type"]
)

DOCUMENT_PROCESS_LATENCY = Histogram(
    "document_process_duration_seconds",
    "Document processing latency",
)


SUCCESS_DOCUMENT_UPLOADED = Counter(
    "document_uploaded_total",
    "Total documents uploaded"
)

DOCUMENT_UPLOAD_FAILED = Counter(
    "document_upload_failed_total",
    "Total documents upload failed"
)

CLAIM_PIPELINE_ERROR = Counter(
    "claim_pipeline_error_total",
    "Total errors in claim pipeline",
)

AGENT_DURATION = Histogram(
    "agent_duration_seconds",
    "Time spent by each agent",
    ["agent"]
)

LLM_CALLS = Counter(
    "llm_calls_total",
    "Total LLM calls"
)

LLM_DURATION = Histogram(
    "llm_duration_seconds",
    "LLM response time"
)