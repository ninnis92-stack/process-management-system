from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from flask import current_app

from ..extensions import db
from ..models import IntegrationEvent
from .tenant_context import get_current_tenant_id


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def publish_event(
    event_name: str,
    payload: dict[str, Any],
    *,
    destination_kind: str = "outbox",
    metadata: dict[str, Any] | None = None,
    provider_key: str | None = None,
    correlation_id: str | None = None,
) -> IntegrationEvent:
    event = IntegrationEvent(
        event_name=event_name,
        destination_kind=destination_kind,
        provider_key=provider_key,
        correlation_id=correlation_id or str(uuid.uuid4()),
        status="pending",
        payload_json=_json_safe(payload),
        metadata_json=_json_safe(metadata or {}),
        next_retry_at=datetime.utcnow(),
        tenant_id=get_current_tenant_id(),
    )
    db.session.add(event)
    db.session.commit()
    return event


def mark_event_delivered(event: IntegrationEvent) -> None:
    event.status = "delivered"
    event.last_attempt_at = datetime.utcnow()
    event.delivered_at = datetime.utcnow()
    event.next_retry_at = None
    db.session.add(event)
    db.session.commit()


def mark_event_failed(event: IntegrationEvent, exc: Exception) -> None:
    now = datetime.utcnow()
    retry_count = int(getattr(event, "retry_count", 0) or 0) + 1
    backoff_minutes = min(5 * (2 ** max(retry_count - 1, 0)), 24 * 60)
    # After a configurable number of retries, mark as permanently failed
    MAX_RETRIES = int(current_app.config.get("INTEGRATION_MAX_RETRIES", 5))
    if retry_count >= MAX_RETRIES:
        event.status = "permanent_failed"
        event.next_retry_at = None
    else:
        event.status = "failed"
    event.last_error = str(exc)
    event.retry_count = retry_count
    event.last_attempt_at = now
    if (
        getattr(event, "next_retry_at", None) is None
        and event.status != "permanent_failed"
    ):
        event.next_retry_at = now + timedelta(minutes=backoff_minutes)
    db.session.add(event)
    db.session.commit()
    try:
        current_app.logger.exception(
            "Integration boundary event failed: %s", event.event_name
        )
    except Exception:
        pass
