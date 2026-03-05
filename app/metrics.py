import logging

try:
    from prometheus_client import Counter, Gauge, generate_latest, CollectorRegistry, CONTENT_TYPE_LATEST, REGISTRY
    METRICS_AVAILABLE = True
except ImportError:
    logging.getLogger(__name__).warning('prometheus_client not installed; metrics disabled')
    METRICS_AVAILABLE = False

    # noop metric implementations so imports elsewhere don't fail
    class _NoopMetric:
        def labels(self, *args, **kwargs):
            return self

        def inc(self, *args, **kwargs):
            return None

        def set(self, *args, **kwargs):
            return None

    def generate_latest(registry=None):
        return b''

    # minimal content-type to return
    CONTENT_TYPE_LATEST = 'text/plain; version=0.0.4'
    REGISTRY = None

    Counter = lambda *a, **k: _NoopMetric()
    Gauge = lambda *a, **k: _NoopMetric()


# Counters
requests_created_total = Counter(
    'app_requests_created_total',
    'Total requests created',
    ['dept']
)

request_transitions_total = Counter(
    'app_request_transitions_total',
    'Request transitions (by from->to and acting dept)',
    ['from_status', 'to_status', 'dept']
)

assignment_changes_total = Counter(
    'app_assignment_changes_total',
    'Assignment changes (assigned/cleared) by dept',
    ['dept', 'action']
)

# Gauges
requests_by_owner = Gauge(
    'app_requests_by_owner',
    'Current requests by owner department',
    ['dept']
)


def metrics_output():
    """Return Prometheus metrics payload (bytes) and content type."""
    try:
        return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
    except Exception:
        return b'', CONTENT_TYPE_LATEST


def update_owner_gauge(session, ReqModel):
    """Query DB to update requests_by_owner gauge."""
    if not METRICS_AVAILABLE:
        return
    # Clear previous values by setting to 0 for all known depts then set
    counts = dict(session.query(ReqModel.owner_department, __import__('sqlalchemy').func.count(ReqModel.id)).group_by(ReqModel.owner_department).all())
    for d, v in counts.items():
        requests_by_owner.labels(dept=d).set(v)
    # Ensure depts with zero get 0
    for d in ('A', 'B', 'C'):
        if d not in counts:
            requests_by_owner.labels(dept=d).set(0)
