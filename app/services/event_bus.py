from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import current_app

from ..extensions import db
from ..models import IntegrationEvent
from .tenant_context import get_current_tenant_id


def publish_event(event_name: str, payload: dict[str, Any], *, destination_kind: str = "outbox", metadata: dict[str, Any] | None = None) -> IntegrationEvent:
    event = IntegrationEvent(
        event_name=event_name,
        destination_kind=destination_kind,
        status="pending",
        payload_json=payload,
        metadata_json=metadata or {},
        tenant_id=get_current_tenant_id(),
    )
    db.session.add(event)
    db.session.commit()
    return event


def mark_event_delivered(event: IntegrationEvent) -> None:
    event.status = "delivered"
    event.delivered_at = datetime.utcnow()
    db.session.add(event)
    db.session.commit()


def mark_event_failed(event: IntegrationEvent, exc: Exception) -> None:
    event.status = "failed"
    event.last_error = str(exc)
    db.session.add(event)
    db.session.commit()
    try:
        current_app.logger.exception("Integration boundary event failed: %s", event.event_name)
    except Exception:
        pass
