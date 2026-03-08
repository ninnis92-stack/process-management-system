from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app

from ..extensions import db
from ..models import Request as ReqModel
from ..models import WebhookSubscription
from .event_bus import publish_event, mark_event_delivered, mark_event_failed


INTEGRATION_KIND_SCAFFOLDS: dict[str, dict[str, Any]] = {
    "ticketing": {
        "label": "Ticketing",
        "description": "Scaffold for external ticket systems such as Jira, ServiceNow, Zendesk, or internal helpdesk APIs.",
        "default_config": {
            "version": "2026-03",
            "provider": "generic_ticketing",
            "capabilities": ["create", "sync_status", "attach_notes"],
            "auth": {"type": "token", "token_env": "", "username_env": ""},
            "endpoints": {"base_url": "", "create": "", "update": "", "lookup": ""},
            "mapping": {"title": "title", "description": "description", "priority": "priority", "status": "status"},
            "compatibility": {"request_format": "json", "response_format": "json", "supports_webhooks": True},
        },
    },
    "webhook": {
        "label": "Webhook",
        "description": "Generic outbound integration scaffold for event subscribers and partner callbacks.",
        "default_config": {
            "version": "2026-03",
            "provider": "generic_webhook",
            "capabilities": ["push_events", "signed_payloads"],
            "auth": {"type": "hmac", "secret_env": "WEBHOOK_SHARED_SECRET"},
            "endpoints": {"url": "", "retry_url": ""},
            "mapping": {"event": "event", "payload": "payload", "sent_at": "sent_at"},
            "compatibility": {"request_format": "json", "signature_header": "X-Webhook-Signature", "supports_retries": True},
        },
    },
    "inventory": {
        "label": "Inventory",
        "description": "Scaffold for SKU, part-number, stock, or catalog integrations.",
        "default_config": {
            "version": "2026-03",
            "provider": "generic_inventory",
            "capabilities": ["validate_part_number", "validate_sales_list", "lookup_stock"],
            "auth": {"type": "token", "token_env": ""},
            "endpoints": {"base_url": "", "part_lookup": "", "sales_lookup": "", "stock_lookup": ""},
            "mapping": {"part_number": "part_number", "sales_list_number": "sales_list_number", "available_count": "available_count"},
            "compatibility": {"request_format": "json", "response_format": "json", "supports_bulk_lookup": True},
        },
    },
    "verification": {
        "label": "Verification",
        "description": "Scaffold for field validation providers and lookup-based verification workflows.",
        "default_config": {
            "version": "2026-03",
            "provider": "generic_verification",
            "capabilities": ["lookup", "validate", "bulk_validate"],
            "auth": {"type": "token", "token_env": ""},
            "endpoints": {"base_url": "", "lookup": "", "validate": ""},
            "mapping": {"input": "value", "ok": "ok", "details": "details"},
            "compatibility": {"request_format": "json", "response_format": "json", "supports_bulk_lookup": True},
        },
    },
}


def _deep_merge_dicts(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def get_integration_scaffold(kind: str) -> dict[str, Any]:
    scaffold = INTEGRATION_KIND_SCAFFOLDS.get((kind or "").strip().lower())
    if scaffold:
        return scaffold
    return {
        "label": (kind or "Integration").title(),
        "description": "Generic future-integration scaffold.",
        "default_config": {
            "version": "2026-03",
            "provider": "generic",
            "capabilities": [],
            "auth": {"type": "none"},
            "endpoints": {},
            "mapping": {},
            "compatibility": {"request_format": "json", "response_format": "json"},
        },
    }


def normalize_integration_config(kind: str, raw_config: str | dict[str, Any] | None) -> dict[str, Any]:
    scaffold = get_integration_scaffold(kind)
    defaults = scaffold.get("default_config") or {}

    if raw_config in (None, ""):
        parsed: dict[str, Any] = {}
    elif isinstance(raw_config, dict):
        parsed = raw_config
    else:
        parsed = json.loads(raw_config)

    if not isinstance(parsed, dict):
        raise ValueError("Integration config must be a JSON object.")

    normalized = _deep_merge_dicts(defaults, parsed)
    normalized["kind"] = (kind or "").strip().lower()
    normalized.setdefault("provider", defaults.get("provider") or "generic")
    normalized.setdefault("version", defaults.get("version") or "2026-03")
    normalized.setdefault("compatibility", defaults.get("compatibility") or {})
    normalized.setdefault("capabilities", defaults.get("capabilities") or [])
    return normalized


def integration_config_summary(raw_config: str | dict[str, Any] | None) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_config) if isinstance(raw_config, str) and raw_config else (raw_config or {})
    except Exception:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return {
        "provider": parsed.get("provider") or "—",
        "version": parsed.get("version") or "—",
        "capabilities": parsed.get("capabilities") or [],
    }


class ExternalDataProvider:
    """Simple adapter interface for pulling data from third-party software."""

    provider_name = "base"

    def fetch(self, *, config: dict[str, Any], query: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError


class EchoProvider(ExternalDataProvider):
    """Default provider for smoke testing integration plumbing."""

    provider_name = "echo"

    def fetch(self, *, config: dict[str, Any], query: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "config": config or {},
            "query": query or {},
            "fetched_at": datetime.utcnow().isoformat() + "Z",
        }


PROVIDERS: dict[str, ExternalDataProvider] = {
    EchoProvider.provider_name: EchoProvider(),
}


def get_provider(name: str) -> ExternalDataProvider:
    provider = PROVIDERS.get((name or "").strip().lower())
    if not provider:
        raise LookupError(f"Unknown integration provider: {name}")
    return provider


def fetch_external_data(provider_name: str, *, config: dict[str, Any] | None = None, query: dict[str, Any] | None = None) -> dict[str, Any]:
    provider = get_provider(provider_name)
    return provider.fetch(config=config or {}, query=query or {})


def _json_default(value: Any):
    if isinstance(value, datetime):
        return value.isoformat() + "Z"
    return str(value)


def _sign_payload(payload: bytes, secret: str | None) -> str | None:
    if not secret:
        return None
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _post_json(url: str, body: dict[str, Any], *, secret: str | None = None, timeout: int = 5) -> None:
    payload = json.dumps(body, default=_json_default).encode("utf-8")
    req = Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "process-management-prototype/1.0")
    signature = _sign_payload(payload, secret)
    if signature:
        req.add_header("X-Webhook-Signature", signature)
    with urlopen(req, timeout=timeout) as resp:  # nosec B310 - admin configured destinations only
        resp.read()


def emit_webhook_event(event_name: str, payload: dict[str, Any]) -> None:
    """Send an event payload to all matching webhook subscribers."""

    boundary_event = publish_event(
        event_name,
        payload,
        destination_kind="webhook",
        metadata={"subscription_count": 0},
    )

    try:
        subscriptions = WebhookSubscription.query.filter_by(active=True).all()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        subscriptions = []

    boundary_event.metadata_json = {
        **(boundary_event.metadata_json or {}),
        "subscription_count": len(subscriptions),
    }
    db.session.add(boundary_event)
    db.session.commit()

    for sub in subscriptions:
        events = sub.events or []
        if events and event_name not in events and "*" not in events:
            continue
        try:
            _post_json(
                sub.url,
                {
                    "event": event_name,
                    "payload": payload,
                    "sent_at": datetime.utcnow(),
                },
                secret=sub.secret,
            )
            mark_event_delivered(boundary_event)
        except (HTTPError, URLError, TimeoutError, ValueError):
            mark_event_failed(boundary_event, Exception(f"Delivery failed for {sub.url}"))
            try:
                current_app.logger.exception(
                    "Failed delivering webhook event '%s' to %s", event_name, sub.url
                )
            except Exception:
                pass


def serialize_request(req: ReqModel) -> dict[str, Any]:
    return {
        "id": req.id,
        "title": req.title,
        "status": req.status,
        "priority": req.priority,
        "owner_department": req.owner_department,
        "requires_c_review": bool(req.requires_c_review),
        "due_at": req.due_at,
        "created_at": req.created_at,
        "updated_at": req.updated_at,
        "assigned_to_user_id": req.assigned_to_user_id,
    }
