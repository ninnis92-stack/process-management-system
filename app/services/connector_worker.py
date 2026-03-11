from __future__ import annotations

import json
from typing import Any

from ..extensions import db
from ..models import IntegrationConfig, IntegrationEvent
from .emailer import EmailService
from .event_bus import mark_event_delivered, mark_event_failed
from .integrations import emit_webhook_event
from .secret_store import resolve_secret_ref
from .slack import SlackService


def process_pending_integration_events(limit: int = 20) -> int:
    """Process pending IntegrationEvent rows (basic dev worker).

    Returns the number of events processed.
    """
    processed = 0
    try:
        from datetime import datetime as _dt

        # include pending events and failed events that are due for retry
        events = (
            IntegrationEvent.query.filter(
                (IntegrationEvent.status == "pending")
                | (
                    (IntegrationEvent.status == "failed")
                    & (IntegrationEvent.next_retry_at <= _dt.utcnow())
                )
            )
            .order_by(
                IntegrationEvent.next_retry_at.asc().nullsfirst(),
                IntegrationEvent.created_at.asc(),
            )
            .limit(limit)
            .all()
        )
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        events = []

    emailer = EmailService()
    slack = SlackService()

    for ev in events:
        try:
            payload = ev.payload_json or {}
            kind = (ev.destination_kind or "outbox").lower()
            provider_key = (ev.provider_key or "").strip() or None
            if kind == "webhook":
                # Prefer explicit provider-config lookup when provider_key present
                cfg = None
                cfg_parsed = None
                try:
                    if provider_key:
                        candidates = IntegrationConfig.query.filter_by(
                            kind="webhook", enabled=True
                        ).all()
                        for c in candidates:
                            try:
                                parsed = json.loads(c.config or "{}")
                            except Exception:
                                parsed = {}
                            # match by explicit key/name in config
                            if (
                                parsed.get("key") == provider_key
                                or parsed.get("name") == provider_key
                            ):
                                cfg = c
                                cfg_parsed = parsed
                                break
                    # fallback: try tenant/department-scoped config via metadata
                    if cfg is None:
                        dept = None
                        try:
                            dept = (ev.metadata_json or {}).get("department") or (
                                payload or {}
                            ).get("request", {}).get("department")
                        except Exception:
                            dept = None
                        if dept:
                            cfg = IntegrationConfig.query.filter_by(
                                kind="webhook", department=dept, enabled=True
                            ).first()
                            if cfg:
                                try:
                                    cfg_parsed = json.loads(cfg.config or "{}")
                                except Exception:
                                    cfg_parsed = {}
                    # final fallback: any enabled webhook config
                    if cfg is None:
                        cfg = IntegrationConfig.query.filter_by(
                            kind="webhook", enabled=True
                        ).first()
                        if cfg:
                            try:
                                cfg_parsed = json.loads(cfg.config or "{}")
                            except Exception:
                                cfg_parsed = {}
                except Exception:
                    cfg = None
                    cfg_parsed = None

                # Determine webhook URL: priority -> payload override -> cfg_parsed.url -> cfg_parsed.webhook_url
                webhook_url = (payload or {}).get("webhook_url") or (payload or {}).get(
                    "slack_webhook"
                )
                if not webhook_url and cfg_parsed:
                    webhook_url = (
                        cfg_parsed.get("url")
                        or cfg_parsed.get("webhook_url")
                        or cfg_parsed.get("endpoint")
                    )
                # resolve secret references via secret_store (env/vault/aws)
                if isinstance(webhook_url, dict) or (
                    isinstance(webhook_url, str)
                    and (
                        webhook_url.startswith("env:")
                        or webhook_url.startswith("vault:")
                        or webhook_url.startswith("aws_secrets_manager:")
                    )
                ):
                    webhook_url = resolve_secret_ref(webhook_url)

                if not webhook_url:
                    # if nothing found, emit generic webhook with payload and let downstream handlers decide
                    emit_webhook_event(ev.event_name, payload)
                    mark_event_delivered(ev)
                else:
                    # emit via integrations helper that expects provider-specific handling
                    emit_webhook_event(ev.event_name, payload, url=webhook_url)
                    mark_event_delivered(ev)
            elif kind == "outbox":
                # Route common automation event types to connectors
                ename = (ev.event_name or "").lower()
                # automation.email -> payload: {to, subject, body}
                if ename.startswith("automation.email") or payload.get("to"):
                    to = payload.get("to")
                    if isinstance(to, (list, tuple)):
                        recipients = list(to)
                    elif isinstance(to, str):
                        recipients = [to]
                    else:
                        recipients = []
                    subj = payload.get("subject") or f"Notification: {ev.event_name}"
                    body = payload.get("body") or str(payload.get("request") or "")
                    res = emailer.send_email(recipients, subj, body)
                    if res.get("ok"):
                        mark_event_delivered(ev)
                    else:
                        raise Exception(res.get("error") or "email_send_failed")
                # slack events
                elif (
                    ename.startswith("automation.slack")
                    or payload.get("channel")
                    or payload.get("slack_webhook")
                ):
                    webhook = payload.get("slack_webhook")
                    text = payload.get("text") or f"Event: {ev.event_name}"
                    # prefer explicit webhook in payload, else try provider-config
                    if not webhook and provider_key:
                        try:
                            cfgs = IntegrationConfig.query.filter_by(
                                kind="webhook", enabled=True
                            ).all()
                            for c in cfgs:
                                try:
                                    parsed = json.loads(c.config or "{}")
                                except Exception:
                                    parsed = {}
                                if (
                                    parsed.get("key") == provider_key
                                    or parsed.get("name") == provider_key
                                ):
                                    webhook = parsed.get("url") or parsed.get(
                                        "webhook_url"
                                    )
                                    break
                        except Exception:
                            webhook = None

                    # If webhook looks like a secret-ref, resolve it
                    if isinstance(webhook, dict) or (
                        isinstance(webhook, str)
                        and (
                            webhook.startswith("env:")
                            or webhook.startswith("vault:")
                            or webhook.startswith("aws_secrets_manager:")
                        )
                    ):
                        webhook = resolve_secret_ref(webhook)
                    if not webhook:
                        raise Exception("missing_slack_webhook_url")
                    slack.post_message(webhook, {"text": text})
                    mark_event_delivered(ev)
                else:
                    # default: mark delivered (observability event)
                    mark_event_delivered(ev)
            else:
                # unknown destination kind -> mark failed
                raise Exception(f"unknown_destination_kind:{kind}")
            processed += 1
        except Exception as exc:  # mark failed and continue
            try:
                mark_event_failed(ev, exc)
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
    return processed
