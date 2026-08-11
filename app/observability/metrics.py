from prometheus_client import Counter, Gauge, Histogram


class Metrics:
    def __init__(self) -> None:
        self.provider_messages = Counter(
            "provider_messages_total", "Provider messages received", ["provider", "type"]
        )
        self.provider_connected = Gauge(
            "provider_connected", "Provider socket connection state", ["provider"]
        )
        self.live_sync = Gauge("live_sync_seconds", "Live synchronization estimates", ["statistic"])
        self.jobs = Gauge("durable_jobs", "Durable jobs by status", ["status"])
        self.worker_restarts = Counter("worker_restart_total", "Worker restart count", ["worker"])
        self.snapshot_latency = Histogram(
            "snapshot_build_latency_seconds", "Decision snapshot build latency"
        )
        self.snapshot_gate_failures = Counter(
            "snapshot_gate_failures_total", "Snapshot gate failures", ["reason"]
        )
        self.ai_requests = Counter("ai_requests_total", "AI requests", ["provider", "status"])
        self.ai_latency = Histogram("ai_latency_seconds", "AI provider latency", ["provider"])
        self.settlement_backlog = Gauge("settlement_backlog", "Maps awaiting settlement")
        self.evaluation_backlog = Gauge("evaluation_backlog", "Decisions awaiting evaluation")
