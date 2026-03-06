"""Prometheus metrics helpers used by the application.

This module exposes Counter and Gauge objects consumed throughout the
codebase. When `prometheus_client` is not installed the module provides a
no-op fallback so instrumentation calls do not raise ImportError and the app
can run without Prometheus available (useful for lightweight local runs).

Metrics provided:
- `requests_created_total` — counter of created requests (label: dept)
- `request_transitions_total` — counter for transitions (labels: from_status,to_status,dept)
- `assignment_changes_total` — counter for assignment/clear actions (labels: dept,action)
- `requests_by_owner` — gauge of current open requests per owner department
"""

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

# New metrics
requests_closed_before_due_total = Counter(
    'app_requests_closed_before_due_total',
    'Requests closed on or before due date',
    ['dept']
)

# Gauges
requests_by_owner = Gauge(
    'app_requests_by_owner',
    'Current requests by owner department',
    ['dept']
)

requests_overdue_by_owner = Gauge(
    'app_requests_overdue_by_owner',
    'Current requests overdue (past due date) by owner department',
    ['dept']
)


def metrics_output():
    """Return Prometheus metrics payload (bytes) and content type.

    This function centralizes generation of the exposition payload and protects
    callers from exceptions that can occur while serializing collector state.
    """
    try:
        return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
    except Exception:
        return b'', CONTENT_TYPE_LATEST


def update_owner_gauge(session, ReqModel):
    """Query DB and refresh the `requests_by_owner` gauge.

    The helper queries the current counts per owner department and sets the
    gauge labels accordingly. When `prometheus_client` is not present this is
    a no-op to avoid depending on metrics for core app behavior.
    """
    if not METRICS_AVAILABLE:
        return

    # Gather counts grouped by owner_department and update the gauge labels.
    counts = dict(
        session.query(ReqModel.owner_department, __import__('sqlalchemy').func.count(ReqModel.id))
        .group_by(ReqModel.owner_department)
        .all()
    )
    for d, v in counts.items():
        requests_by_owner.labels(dept=d).set(v)

    # Make sure departments with zero items are explicitly set to 0 so Prometheus
    # scraped series don't linger with stale samples in the registry.
    for d in ('A', 'B', 'C'):
        if d not in counts:
            requests_by_owner.labels(dept=d).set(0)

    # Also update overdue counts: requests where due_at is set, due_at < now, and not CLOSED
    try:
        from datetime import datetime
        func = __import__('sqlalchemy').func
        overdue_counts = dict(
            session.query(ReqModel.owner_department, func.count(ReqModel.id))
            .filter(ReqModel.due_at != None)
            .filter(ReqModel.due_at < datetime.utcnow())
            .filter(ReqModel.status != 'CLOSED')
            .group_by(ReqModel.owner_department)
            .all()
        )
        for d, v in overdue_counts.items():
            requests_overdue_by_owner.labels(dept=d).set(v)
        for d in ('A', 'B', 'C'):
            if d not in overdue_counts:
                requests_overdue_by_owner.labels(dept=d).set(0)
    except Exception:
        # Do not let metrics failures affect app
        pass
