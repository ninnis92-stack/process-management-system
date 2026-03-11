from flask import Blueprint, jsonify, render_template_string, request

from app import csrf
from app.models import AutomationRule
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
    try:
        templates = list_templates_payload()
        if not isinstance(templates, list):
            return jsonify({"ok": False, "error": "invalid_response", "code": 500, "message": "Templates payload must be a list."}), 500
        return jsonify({"ok": True, "templates": templates})
    except Exception as exc:
        return jsonify({"ok": False, "error": "internal_error", "code": 500, "message": str(exc)}), 500


@csrf.exempt
@api_v1_bp.route("/templates/<int:template_id>/verify", methods=["POST"])
def template_verify(template_id: int):
    if not _check_api_key(request):
        return jsonify({"ok": False, "error": "auth_required", "code": 401, "message": "API key required."}), 401
    data = request.get_json() or {}
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "invalid_input", "code": 400, "message": "Input must be a JSON object."}), 400
    try:
        return jsonify(verify_template_payload(template_id, data))
    except Exception as exc:
        return jsonify({"ok": False, "error": "internal_error", "code": 500, "message": str(exc)}), 500


@api_v1_bp.route("/templates/<int:template_id>/external-schema", methods=["GET"])
def template_external_schema(template_id: int):
    if not _check_api_key(request):
        return jsonify({"ok": False, "error": "auth_required", "code": 401, "message": "API key required."}), 401
    try:
        return jsonify(template_external_schema_payload(template_id))
    except Exception as exc:
        return jsonify({"ok": False, "error": "internal_error", "code": 500, "message": str(exc)}), 500


@api_v1_bp.route("/requests", methods=["GET"])
def requests_list():
    if not _check_api_key(request):
        return jsonify({"ok": False, "error": "auth_required", "code": 401, "message": "API key required."}), 401
    department = (request.args.get("department") or "").strip().upper()
    status = (request.args.get("status") or "").strip()
    try:
        limit = int(request.args.get("limit", 50))
        if limit < 1 or limit > 250:
            return jsonify({"ok": False, "error": "invalid_limit", "code": 400, "message": "Limit must be between 1 and 250."}), 400
    except Exception:
        return jsonify({"ok": False, "error": "invalid_limit", "code": 400, "message": "Limit must be an integer."}), 400
    try:
        payload = list_requests_payload(
            department=department or None,
            status=status or None,
            limit=limit,
        )
        return jsonify({"ok": True, "requests": payload})
    except Exception as exc:
        return jsonify({"ok": False, "error": "internal_error", "code": 500, "message": str(exc)}), 500


@api_v1_bp.route("/requests/<int:request_id>", methods=["GET"])
def request_detail(request_id: int):
    if not _check_api_key(request):
        return jsonify({"ok": False, "error": "auth_required", "code": 401, "message": "API key required."}), 401
    try:
        return jsonify(request_detail_payload(request_id))
    except Exception as exc:
        return jsonify({"ok": False, "error": "internal_error", "code": 500, "message": str(exc)}), 500


@api_v1_bp.route("/template-swap", methods=["GET"])
def template_swap():
    template_id = request.args.get("template_id", type=int)
    field = (request.args.get("field") or "").strip()
    value = (request.args.get("value") or "").strip()
    if not template_id or not field:
        return jsonify({"ok": False, "error": "missing_params", "code": 400, "message": "template_id and field are required."}), 400
    try:
        return jsonify(template_swap_payload(template_id, field, value))
    except Exception as exc:
        return jsonify({"ok": False, "error": "internal_error", "code": 500, "message": str(exc)}), 500


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


@api_v1_bp.route("/docs", methods=["GET"])
def api_docs():
    """Serve a minimal Swagger UI pointing at the versioned OpenAPI document."""
    return render_template_string(
        """
        <!doctype html>
        <html lang='en'>
        <head>
            <meta charset='utf-8' />
            <meta name='viewport' content='width=device-width, initial-scale=1' />
            <title>Process Management API Docs</title>
            <link rel='stylesheet' href='https://unpkg.com/swagger-ui-dist@4/swagger-ui.css' />
            <style>
                html, body { height: 100%; margin: 0; padding: 0; background: #f7f8fa; }
                #swagger-ui { max-width: 900px; margin: 40px auto; box-shadow: 0 2px 16px rgba(0,0,0,0.08); border-radius: 12px; background: #fff; padding: 32px 24px; }
                .topbar { display: none !important; }
                .brand-header {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin-bottom: 32px;
                }
                .brand-logo {
                    width: 48px;
                    height: 48px;
                    margin-right: 16px;
                }
                .brand-title {
                    font-size: 2.2rem;
                    font-weight: 700;
                    color: #22223b;
                    letter-spacing: 0.02em;
                }
                .brand-desc {
                    font-size: 1.1rem;
                    color: #4a4a6a;
                    margin-top: 8px;
                    text-align: center;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                }
                .links-bar {
                    display: flex;
                    justify-content: center;
                    gap: 24px;
                    margin-bottom: 24px;
                }
                .links-bar a {
                    color: #22223b;
                    font-weight: 500;
                    text-decoration: none;
                    padding: 8px 16px;
                    border-radius: 6px;
                    background: #e9e9f3;
                    transition: background 0.2s;
                }
                .links-bar a:hover {
                    background: #d1d1e9;
                }
                .dark-mode-toggle {
                    position: fixed;
                    top: 16px;
                    right: 16px;
                    z-index: 1000;
                    background: #22223b;
                    color: #fff;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 16px;
                    cursor: pointer;
                    font-size: 1rem;
                }
                @media (max-width: 600px) {
                    #swagger-ui { padding: 8px 2px; }
                    .brand-title { font-size: 1.2rem; }
                    .brand-logo { width: 32px; height: 32px; }
                    .links-bar { gap: 8px; }
                    .brand-desc {
                        font-size: 0.95rem;
                        margin-top: 4px;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        width: 100vw;
                        min-height: 32px;
                    }
                }
            </style>
        </head>
        <body>
            <button class='dark-mode-toggle' onclick='toggleDarkMode()'>Toggle Dark Mode</button>
            <div class='brand-header'>
                <img class='brand-logo' src='https://raw.githubusercontent.com/naheeminnis/process-management-prototype/main/design/logo.svg' alt='Logo' />
                <span class='brand-title'>Process Management API</span>
            </div>
            <div class='brand-desc'>
                Clean, powerful, and intuitive API documentation for all your process automation needs.
            </div>
            <div class='links-bar'>
                <a href='https://github.com/naheeminnis/process-management-prototype' target='_blank'>GitHub Repo</a>
                <a href='https://raw.githubusercontent.com/naheeminnis/process-management-prototype/main/docs/README_FULL.md' target='_blank'>Full Docs</a>
                <a href='mailto:support@process-management.com'>Support</a>
            </div>
            <div id='swagger-ui'></div>
            <script src='https://unpkg.com/swagger-ui-dist@4/swagger-ui-bundle.js'></script>
            <script>
                function toggleDarkMode() {
                    const body = document.body;
                    body.classList.toggle('dark-mode');
                    if (body.classList.contains('dark-mode')) {
                        body.style.background = '#22223b';
                        document.querySelector('#swagger-ui').style.background = '#2a2a3c';
                        document.querySelector('#swagger-ui').style.color = '#fff';
                    } else {
                        body.style.background = '#f7f8fa';
                        document.querySelector('#swagger-ui').style.background = '#fff';
                        document.querySelector('#swagger-ui').style.color = '#22223b';
                    }
                }
                window.onload = function() {
                    const ui = SwaggerUIBundle({
                        url: {{ spec_url|tojson }},
                        dom_id: '#swagger-ui',
                        deepLinking: true,
                        presets: [SwaggerUIBundle.presets.apis],
                        layout: "BaseLayout",
                    });
                    window.ui = ui;
                };
            </script>
        </body>
        </html>
        """,
        spec_url="/api/v1/openapi.json",
    )


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
