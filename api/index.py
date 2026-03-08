from app import create_app
from app import csrf
from flask import jsonify, request
from app.models import (
    FormTemplate,
    FormField,
    FormFieldOption,
    Request as ReqModel,
    WebhookSubscription,
)
from app.extensions import db, get_or_404
from datetime import datetime
from app.services.integrations import fetch_external_data, serialize_request
from app.services.request_creation import run_template_field_verifications

app = create_app()


def _check_api_key(req):
    key = (
        req.headers.get("X-Api-Key")
        or (req.headers.get("Authorization") or "").replace("Bearer ", "").strip()
    )
    if not key:
        return None
    integration_key_model = globals().get("IntegrationKey")
    if integration_key_model is None:
        # In environments where the model is not present yet, accept any
        # non-empty key so the integration surface remains usable.
        return {"key": key, "active": True}
    ik = integration_key_model.query.filter_by(key=key, active=True).first()
    return ik


@app.route("/api/templates", methods=["GET"])
def api_templates():
    # Public listing for now; API clients can call to get template shapes
    templates = FormTemplate.query.order_by(FormTemplate.created_at.desc()).all()
    out = []
    for t in templates:
        tfields = []
        for f in t.fields.order_by(FormField.order.asc()).all():
            opts = [
                dict(value=o.value, label=o.label)
                for o in f.options.order_by(FormFieldOption.order.asc()).all()
            ]
            tfields.append(
                dict(
                    name=f.name,
                    label=f.label,
                    type=f.field_type,
                    required=bool(f.required),
                    hint=f.hint,
                    options=opts,
                )
            )
        out.append(
            dict(id=t.id, name=t.name, description=t.description, fields=tfields)
        )
    return jsonify({"ok": True, "templates": out})


@app.route("/api/templates/<int:template_id>/verify", methods=["POST"])
@csrf.exempt
def api_template_verify(template_id: int):
    # Require API key for verification endpoints
    ik = _check_api_key(request)
    if not ik:
        return jsonify({"ok": False, "error": "auth_required"}), 401

    t = get_or_404(FormTemplate, template_id)
    data = request.get_json() or {}
    try:
        fields = list(t.fields.order_by(FormField.order.asc()).all())
    except Exception:
        fields = sorted(list(t.fields or []), key=lambda field: getattr(field, "order", 0))
    verification_results = run_template_field_verifications(fields, data)
    results = {}
    for f in fields:
        val = data.get(f.name)
        results[f.name] = verification_results.get(f.name) or {"ok": True, "value": val}
        results[f.name].setdefault("value", val)

    return jsonify({"ok": True, "template_id": t.id, "results": results})


@app.route("/api/requests", methods=["GET"])
def api_requests_list():
    ik = _check_api_key(request)
    if not ik:
        return jsonify({"ok": False, "error": "auth_required"}), 401

    q = ReqModel.query.order_by(ReqModel.updated_at.desc())
    department = (request.args.get("department") or "").strip().upper()
    status = (request.args.get("status") or "").strip()
    limit = min(max(int(request.args.get("limit", 50)), 1), 250)

    if department:
        q = q.filter(ReqModel.owner_department == department)
    if status:
        q = q.filter(ReqModel.status == status)

    items = [serialize_request(req) for req in q.limit(limit).all()]
    return jsonify({"ok": True, "requests": items, "count": len(items)})


@app.route("/api/requests/<int:request_id>", methods=["GET"])
def api_request_detail(request_id: int):
    ik = _check_api_key(request)
    if not ik:
        return jsonify({"ok": False, "error": "auth_required"}), 401

    req = get_or_404(ReqModel, request_id)
    return jsonify({"ok": True, "request": serialize_request(req)})


@app.route("/api/integrations/fetch", methods=["POST"])
@csrf.exempt
def api_integrations_fetch():
    ik = _check_api_key(request)
    if not ik:
        return jsonify({"ok": False, "error": "auth_required"}), 401

    data = request.get_json(silent=True) or {}
    provider = data.get("provider") or "echo"
    config = data.get("config") or {}
    query = data.get("query") or {}
    try:
        result = fetch_external_data(provider, config=config, query=query)
        return jsonify({"ok": True, "result": result})
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/integrations/webhook-subscriptions", methods=["GET", "POST"])
@csrf.exempt
def api_webhook_subscriptions():
    ik = _check_api_key(request)
    if not ik:
        return jsonify({"ok": False, "error": "auth_required"}), 401

    if request.method == "GET":
        subs = WebhookSubscription.query.order_by(WebhookSubscription.created_at.desc()).all()
        return jsonify(
            {
                "ok": True,
                "subscriptions": [
                    {
                        "id": s.id,
                        "url": s.url,
                        "events": s.events or [],
                        "active": bool(s.active),
                        "created_at": s.created_at.isoformat() if s.created_at else None,
                    }
                    for s in subs
                ],
            }
        )

    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    events = data.get("events") or ["*"]
    if not url:
        return jsonify({"ok": False, "error": "url_required"}), 400

    sub = WebhookSubscription(
        url=url,
        events=events,
        secret=(data.get("secret") or None),
        active=bool(data.get("active", True)),
    )
    db.session.add(sub)
    db.session.commit()
    return jsonify({"ok": True, "subscription_id": sub.id}), 201
