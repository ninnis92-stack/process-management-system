"""Simple automation rule engine and action dispatcher.

This service provides a small, local evaluator to run `AutomationRule`s when
events occur. It intentionally keeps behavior simple because a more robust
workflow engine may be added later; rules execute synchronously here and
emit integration boundary events for outbound actions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..extensions import db
from ..models import AutomationRule
from ..models import Request as ReqModel
from .event_bus import publish_event
from .integrations import serialize_request


def evaluate_rules_for_event(event_name: str, request_obj: ReqModel) -> list[int]:
    """Find active rules that are triggered by `event_name` and run them.

    Returns list of rule ids that fired.
    """
    fired: list[int] = []
    try:
        tenant_id = getattr(request_obj, "tenant_id", None)
        query = AutomationRule.query.filter_by(is_active=True)
        # prefer tenant-scoped rules but include global (tenant_id is NULL)
        rules = query.filter(
            (AutomationRule.tenant_id == tenant_id) | (AutomationRule.tenant_id == None)
        ).all()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        rules = []

    for rule in rules:
        triggers = rule.triggers_json or []
        if triggers and event_name not in triggers and "*" not in triggers:
            continue
        if not rule.matches_request(request_obj):
            continue
        try:
            execute_rule_actions(rule, request_obj, event_name=event_name)
            fired.append(rule.id)
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
    return fired


def execute_rule_actions(
    rule: AutomationRule, request_obj: ReqModel, *, event_name: str | None = None
) -> None:
    """Execute declared actions for a matching rule.

    Actions are simple dicts with an `action` key. We persist an
    `IntegrationEvent` via `publish_event` for outbound work where appropriate.
    """
    actions = rule.actions_json or []
    payload_root = serialize_request(request_obj)
    for action in actions:
        kind = (action.get("action") or "").strip().lower()
        if kind == "webhook":
            event = action.get("event_name") or f"automation.{rule.id}.webhook"
            publish_event(
                event,
                {"rule_id": rule.id, "request": payload_root},
                destination_kind="webhook",
            )
        elif kind == "email":
            # emit to outbox for downstream emailer worker
            to = action.get("to")
            publish_event(
                "automation.email",
                {"rule_id": rule.id, "to": to, "request": payload_root},
                destination_kind="outbox",
            )
        elif kind == "change_status":
            new_status = action.get("status")
            if new_status:
                request_obj.status = new_status
                request_obj.updated_at = datetime.utcnow()
                db.session.add(request_obj)
                db.session.commit()
                publish_event(
                    "request.status_changed",
                    {"rule_id": rule.id, "request": payload_root},
                    destination_kind="outbox",
                )
        elif kind == "escalate":
            # escalate: publish an integration event that can be processed by rules
            publish_event(
                "automation.escalation",
                {"rule_id": rule.id, "request": payload_root},
                destination_kind="outbox",
            )
        elif kind == "assign_user":
            user_id = action.get("user_id")
            if user_id:
                request_obj.assigned_to_user_id = int(user_id)
                request_obj.updated_at = datetime.utcnow()
                db.session.add(request_obj)
                db.session.commit()
                publish_event(
                    "request.assignment_changed",
                    {"rule_id": rule.id, "request": payload_root},
                    destination_kind="outbox",
                )
        else:
            # unknown action: publish a generic automation event for observability
            publish_event(
                "automation.unknown_action",
                {"rule_id": rule.id, "action": action, "request": payload_root},
                destination_kind="outbox",
            )
