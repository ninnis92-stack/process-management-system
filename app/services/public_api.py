from __future__ import annotations

from typing import Any

from app.api.v1.schemas import RequestSchema, TemplateSchema
from app.extensions import db, get_or_404
from app.models import FormTemplate, Request as ReqModel, TemplateSwapRule, WebhookSubscription
from app.services.integrations import fetch_external_data, serialize_request
from app.services.request_creation import (
    build_template_spec,
    group_template_spec_by_section,
    run_template_field_verifications,
)


def list_templates_payload() -> dict[str, Any]:
    templates = FormTemplate.query.order_by(FormTemplate.created_at.desc()).all()
    items = []
    for template in templates:
        fields = []
        for field in sorted(
            list(getattr(template, "fields", [])),
            key=lambda row: getattr(row, "order", 0),
        ):
            options = [
                {"value": option.value, "label": option.label}
                for option in sorted(
                    list(getattr(field, "options", [])),
                    key=lambda row: getattr(row, "order", 0),
                )
            ]
            fields.append(
                {
                    "name": field.name,
                    "label": field.label,
                    "type": field.field_type,
                    "required": bool(field.required),
                    "hint": field.hint,
                    "options": options,
                }
            )
        items.append(
            {
                "id": template.id,
                "name": template.name,
                "description": template.description,
                "layout": getattr(template, "layout", "standard"),
                "fields": fields,
            }
        )
    return {"ok": True, "templates": TemplateSchema(many=True).dump(items)}


def verify_template_payload(template_id: int, data: dict[str, Any]) -> dict[str, Any]:
    template = get_or_404(FormTemplate, template_id)
    try:
        fields = sorted(list(template.fields), key=lambda row: getattr(row, "order", 0))
    except Exception:
        fields = sorted(list(template.fields or []), key=lambda row: getattr(row, "order", 0))
    verification_results = run_template_field_verifications(fields, data)
    results = {}
    for field in fields:
        value = data.get(field.name)
        result = verification_results.get(field.name) or {"ok": True, "value": value}
        result.setdefault("value", value)
        results[field.name] = result
    return {
        "ok": True,
        "template_id": template.id,
        "layout": getattr(template, "layout", "standard"),
        "results": results,
    }


def template_external_schema_payload(template_id: int) -> dict[str, Any]:
    template = get_or_404(FormTemplate, template_id)
    fields = sorted(
        list(getattr(template, "fields", []) or []),
        key=lambda row: getattr(row, "order", 0),
    )
    spec = build_template_spec(
        fields,
        verification_prefill_enabled=bool(
            getattr(template, "verification_prefill_enabled", False)
        ),
    )
    return {
        "ok": True,
        "template": {
            "id": template.id,
            "name": template.name,
            "description": template.description,
            "layout": getattr(template, "layout", "standard"),
            "layout_label": getattr(template, "layout_label", "Standard"),
            "external_enabled": bool(getattr(template, "external_enabled", False)),
            "external_provider": getattr(template, "external_provider", None),
            "external_form_id": getattr(template, "external_form_id", None),
            "external_form_url": getattr(template, "external_form_url", None),
            "fields": spec,
            "sections": group_template_spec_by_section(spec),
        },
    }


def list_requests_payload(
    *, department: str | None = None, status: str | None = None, limit: int = 50
) -> dict[str, Any]:
    query = ReqModel.query.order_by(ReqModel.updated_at.desc())
    if department:
        query = query.filter(ReqModel.owner_department == department)
    if status:
        query = query.filter(ReqModel.status == status)
    items = [serialize_request(row) for row in query.limit(limit).all()]
    serialized = RequestSchema(many=True).dump(items)
    return {"ok": True, "requests": serialized, "count": len(serialized)}


def request_detail_payload(request_id: int) -> dict[str, Any]:
    request_obj = get_or_404(ReqModel, request_id)
    return {"ok": True, "request": RequestSchema().dump(serialize_request(request_obj))}


def template_swap_payload(template_id: int, field: str, value: str) -> dict[str, Any]:
    rule = TemplateSwapRule.query.filter_by(
        template_id=template_id,
        trigger_field_name=field,
        trigger_value=value,
    ).first()
    if not rule:
        return {"ok": True, "swap": False}
    template = get_or_404(FormTemplate, rule.target_template_id)
    fields = sorted(
        list(getattr(template, "fields", []) or []),
        key=lambda row: getattr(row, "order", 0),
    )
    spec = build_template_spec(
        fields,
        verification_prefill_enabled=bool(
            getattr(template, "verification_prefill_enabled", False)
        ),
    )
    return {
        "ok": True,
        "swap": True,
        "template": {"id": template.id, "fields": spec},
    }


def fetch_integration_payload(
    provider: str, config: dict[str, Any] | None, query: dict[str, Any] | None
) -> dict[str, Any]:
    result = fetch_external_data(provider, config=config, query=query)
    return {"ok": True, "result": result}


def list_webhook_subscriptions_payload() -> dict[str, Any]:
    subscriptions = WebhookSubscription.query.order_by(
        WebhookSubscription.created_at.desc()
    ).all()
    return {
        "ok": True,
        "subscriptions": [
            {"id": row.id, "url": row.url, "events": row.events}
            for row in subscriptions
        ],
    }


def create_webhook_subscription_payload(
    url: str, events: list[str]
) -> tuple[dict[str, Any], int]:
    subscription = WebhookSubscription(url=url, events=events)
    db.session.add(subscription)
    db.session.commit()
    return {"ok": True, "id": subscription.id}, 201


def openapi_spec() -> dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Process Management Prototype API",
            "version": "v1",
            "description": "Versioned public API for templates, requests, and integration tooling.",
        },
        "servers": [{"url": "/api/v1"}],
        "components": {
            "securitySchemes": {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-Api-Key",
                }
            }
        },
        "paths": {
            "/templates": {
                "get": {
                    "summary": "List templates",
                    "security": [{"ApiKeyAuth": []}],
                }
            },
            "/templates/{template_id}/verify": {
                "post": {
                    "summary": "Verify template field payload",
                    "security": [{"ApiKeyAuth": []}],
                }
            },
            "/templates/{template_id}/external-schema": {
                "get": {
                    "summary": "Get external form schema for a template",
                    "security": [{"ApiKeyAuth": []}],
                }
            },
            "/requests": {
                "get": {
                    "summary": "List requests",
                    "security": [{"ApiKeyAuth": []}],
                }
            },
            "/requests/{request_id}": {
                "get": {
                    "summary": "Get request detail",
                    "security": [{"ApiKeyAuth": []}],
                }
            },
            "/template-swap": {
                "get": {"summary": "Resolve template swap rules"}
            },
            "/integrations/fetch": {
                "post": {
                    "summary": "Fetch data from an external provider",
                    "security": [{"ApiKeyAuth": []}],
                }
            },
            "/integrations/webhook-subscriptions": {
                "get": {
                    "summary": "List webhook subscriptions",
                    "security": [{"ApiKeyAuth": []}],
                },
                "post": {
                    "summary": "Create a webhook subscription",
                    "security": [{"ApiKeyAuth": []}],
                },
            },
            "/openapi.json": {
                "get": {"summary": "Return the OpenAPI document for this API"}
            },
        },
    }