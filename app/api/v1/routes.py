import os
from datetime import datetime

from flask import Blueprint, jsonify, request

from app import csrf
from app.services.public_api import (
    create_webhook_subscription_payload,
    fetch_integration_payload,
    list_requests_payload,
    list_templates_payload,
    list_webhook_subscriptions_payload,
    openapi_spec,
    request_detail_payload,
    template_external_schema_payload,
    template_swap_payload,
    verify_template_payload,
)

from app.models import AutomationRule
from app.services.rule_engine import evaluate_rules_for_event

api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")


def _check_api_key(req):
    key = (
        req.headers.get("X-Api-Key")
        or (req.headers.get("Authorization") or "").replace("Bearer ", "").strip()
    )
    if not key:
        return None
    integration_key_model = globals().get("IntegrationKey")
    if integration_key_model is None:
        return {"key": key, "active": True}
    return integration_key_model.query.filter_by(key=key, active=True).first()


@api_v1_bp.route("/templates", methods=["GET"])
def templates_list():
    return jsonify(list_templates_payload())


@csrf.exempt
@api_v1_bp.route("/templates/<int:template_id>/verify", methods=["POST"])
def template_verify(template_id: int):
    if not _check_api_key(request):
        return jsonify({"ok": False, "error": "auth_required"}), 401
    return jsonify(verify_template_payload(template_id, request.get_json() or {}))


@api_v1_bp.route("/templates/<int:template_id>/external-schema", methods=["GET"])
def template_external_schema(template_id: int):
    if not _check_api_key(request):
        return jsonify({"ok": False, "error": "auth_required"}), 401
    return jsonify(template_external_schema_payload(template_id))


@api_v1_bp.route("/requests", methods=["GET"])
def requests_list():
    if not _check_api_key(request):
        return jsonify({"ok": False, "error": "auth_required"}), 401
    department = (request.args.get("department") or "").strip().upper()
    status = (request.args.get("status") or "").strip()
    limit = min(max(int(request.args.get("limit", 50)), 1), 250)
    return jsonify(
        list_requests_payload(
            department=department or None,
            status=status or None,
            limit=limit,
        )
    )


@api_v1_bp.route("/requests/<int:request_id>", methods=["GET"])
def request_detail(request_id: int):
    if not _check_api_key(request):
        return jsonify({"ok": False, "error": "auth_required"}), 401
    return jsonify(request_detail_payload(request_id))


@api_v1_bp.route("/template-swap", methods=["GET"])
def template_swap():
    template_id = request.args.get("template_id", type=int)
    field = (request.args.get("field") or "").strip()
    value = (request.args.get("value") or "").strip()
    if not template_id or not field:
        return jsonify({"ok": False, "error": "missing_params"}), 400
    return jsonify(template_swap_payload(template_id, field, value))


@csrf.exempt
@api_v1_bp.route("/integrations/fetch", methods=["POST"])
def integrations_fetch():
    if not _check_api_key(request):
        return jsonify({"ok": False, "error": "auth_required"}), 401
    data = request.get_json() or {}
    try:
        return jsonify(
            fetch_integration_payload(
                data.get("provider"),
                data.get("config"),
                data.get("query"),
            )
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@csrf.exempt
@api_v1_bp.route("/integrations/webhook-subscriptions", methods=["GET", "POST"])
def webhook_subscriptions():
    if not _check_api_key(request):
        return jsonify({"ok": False, "error": "auth_required"}), 401
    if request.method == "GET":
        return jsonify(list_webhook_subscriptions_payload())
    data = request.get_json() or {}
    url = data.get("url")
    events = data.get("events")
    if not url or not events:
        return jsonify({"ok": False, "error": "missing_params"}), 400
    payload, status_code = create_webhook_subscription_payload(url, events)
    return jsonify(payload), status_code


@api_v1_bp.route("/openapi.json", methods=["GET"])
def api_openapi_document():
    return jsonify(openapi_spec())


@csrf.exempt
@api_v1_bp.route("/automation-rules", methods=["GET", "POST"])
def automation_rules_list_create():
    if request.method == "GET":
        rules = AutomationRule.query.all()
        out = [
            {
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "triggers": r.triggers_json,
                "conditions": r.conditions_json,
                "actions": r.actions_json,
                "is_active": bool(r.is_active),
            }
            for r in rules
        ]
        return jsonify({"ok": True, "rules": out})
    # POST: create new rule (requires API key)
    if not _check_api_key(request):
        return jsonify({"ok": False, "error": "auth_required"}), 401
    data = request.get_json() or {}
    r = AutomationRule(
        name=data.get("name") or "unnamed rule",
        description=data.get("description"),
        triggers_json=data.get("triggers") or [],
        conditions_json=data.get("conditions") or {},
        actions_json=data.get("actions") or [],
        is_active=bool(data.get("is_active", True)),
    )
    db = __import__("app").models.db
    db.session.add(r)
    db.session.commit()
    return jsonify({"ok": True, "id": r.id}), 201


@csrf.exempt
@api_v1_bp.route("/automation-rules/<int:rule_id>/fire", methods=["POST"])
def automation_rule_fire(rule_id: int):
    # Fire a rule against a request id supplied in JSON: {request_id: INT}
    if not _check_api_key(request):
        return jsonify({"ok": False, "error": "auth_required"}), 401
    data = request.get_json() or {}
    req_id = data.get("request_id")
    if not req_id:
        return jsonify({"ok": False, "error": "missing_params"}), 400
    from app.models import Request as ReqModel

    req = ReqModel.query.filter_by(id=int(req_id)).first()
    if not req:
        return jsonify({"ok": False, "error": "not_found"}), 404
    rule = AutomationRule.query.filter_by(id=rule_id).first()
    if not rule:
        return jsonify({"ok": False, "error": "rule_not_found"}), 404
    fired = []
    try:
        if rule.matches_request(req):
            evaluate_rules_for_event("manual_fire", req)
            fired = [rule.id]
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "fired": fired})
