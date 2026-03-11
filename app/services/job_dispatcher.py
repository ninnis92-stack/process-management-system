from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from flask import current_app

from ..extensions import db
from ..models import JobRecord
from .tenant_context import get_current_tenant_id


def run_job(
    job_name: str,
    handler: Callable[..., Any],
    *args,
    queue_name: str = "default",
    payload: dict | None = None,
    **kwargs,
):
    """Persist a job run and execute it synchronously for now.

    This gives the app a durable job ledger before a queue backend is wired in.
    """
    record = JobRecord(
        job_name=job_name,
        queue_name=queue_name,
        status="queued",
        payload_json=payload or {},
        tenant_id=get_current_tenant_id(),
    )
    db.session.add(record)
    db.session.commit()

    record.status = "running"
    record.started_at = datetime.utcnow()
    db.session.add(record)
    db.session.commit()

    try:
        result = handler(*args, **kwargs)
        record.status = "completed"
        record.result_json = (
            result
            if isinstance(result, dict)
            else {"result": str(result) if result is not None else ""}
        )
        record.finished_at = datetime.utcnow()
        db.session.add(record)
        db.session.commit()
        return result
    except Exception as exc:
        record.status = "failed"
        record.error_text = str(exc)
        record.finished_at = datetime.utcnow()
        record.retry_count = int(record.retry_count or 0) + 1
        db.session.add(record)
        db.session.commit()
        try:
            current_app.logger.exception("Job %s failed", job_name)
        except Exception:
            pass
        raise
