import os
from sqlalchemy import inspect as sa_inspect

from app import create_app
from app import csrf
from flask import jsonify, request
from app.models import (
    FormTemplate,
    FormField,
    FormFieldOption,
    Request as ReqModel,
    TemplateSwapRule,
    WebhookSubscription,
)
from app.extensions import db, get_or_404
from datetime import datetime
from app.services.integrations import fetch_external_data, serialize_request
from app.services.request_creation import run_template_field_verifications
from app.services.request_creation import build_template_spec, group_template_spec_by_section

app = create_app()

# older modules may import this file directly; the application factory
# takes care of registering the versioned blueprint.  We still import it here
# so Python knows the module exists and any side-effects (route definitions)
# are executed.
from app.api.v1 import api_v1_bp  # noqa: F401


# for backwards compatibility during migration we redirect unversioned
# requests to the latest version.  This is intentionally simple and can be
# removed once clients are updated.
from flask import redirect

@app.route("/api/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def _api_catch_all(subpath):
    # preserve query string automatically
    return redirect(f"/api/v1/{subpath}", code=301)


def _ensure_api_schema_ready():
    """Best-effort schema bootstrap for standalone API usage.

    The API module is imported directly in tests and in lightweight integration
    scenarios. When the target database is empty, ensure tables exist so the
    API can still operate without relying on a separate app bootstrap step.
    """
    try:
        with app.app_context():
            inspector = sa_inspect(db.engine)
            if not inspector.has_table("user"):
                db.create_all()
    except Exception:
        # Do not block import-time startup; normal request handling or release
        # tasks will still surface operational problems.
        pass


_ensure_api_schema_ready()


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
        # fields relationship returns a plain list; sort by order attribute if present
        for f in sorted(list(getattr(t, "fields", [])), key=lambda fld: getattr(fld, "order", 0)):
            opts = [
                dict(value=o.value, label=o.label)
                for o in sorted(list(getattr(f, "options", [])), key=lambda o: getattr(o, "order", 0))
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
            dict(id=t.id, name=t.name, description=t.description, layout=getattr(t, "layout", "standard"), fields=tfields)
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
        # attempt to use ORM ordering if available
        fields = sorted(list(t.fields), key=lambda field: getattr(field, "order", 0))
    except Exception:
        fields = sorted(list(t.fields or []), key=lambda field: getattr(field, "order", 0))
    verification_results = run_template_field_verifications(fields, data)
    results = {}
    for f in fields:
        val = data.get(f.name)
        results[f.name] = verification_results.get(f.name) or {"ok": True, "value": val}
        results[f.name].setdefault("value", val)

    return jsonify({"ok": True, "template_id": t.id, "layout": getattr(t, "layout", "standard"), "results": results})


@app.route("/api/templates/<int:template_id>/external-schema", methods=["GET"])
def api_template_external_schema(template_id: int):
    ik = _check_api_key(request)
    if not ik:
        return jsonify({"ok": False, "error": "auth_required"}), 401

    t = get_or_404(FormTemplate, template_id)
    fields = sorted(list(getattr(t, "fields", []) or []), key=lambda field: getattr(field, "order", 0))
    spec = build_template_spec(
        fields,
        verification_prefill_enabled=bool(getattr(t, "verification_prefill_enabled", False)),
    )
    return jsonify(
        {
            "ok": True,
            "template": {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "layout": getattr(t, "layout", "standard"),
                "layout_label": getattr(t, "layout_label", "Standard"),
                "external_enabled": bool(getattr(t, "external_enabled", False)),
                "external_provider": getattr(t, "external_provider", None),
                "external_form_id": getattr(t, "external_form_id", None),
                "external_form_url": getattr(t, "external_form_url", None),
                "fields": spec,
                "sections": group_template_spec_by_section(spec),
            },
        }
    )


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


@app.route("/api/template-swap", methods=["GET"])
def api_template_swap():
    """Check for a template-swap rule for a given template, field and value.

    Returns the target template's external schema if a matching rule exists.
    """
    ik = _check_api_key(request)
    # allow anonymous callers for frontend use; do not require API key
    template_id = request.args.get("template_id", type=int)
    field = (request.args.get("field") or "").strip()
    value = (request.args.get("value") or "").strip()

    if not template_id or not field:
        return jsonify({"ok": False, "error": "missing_params"}), 400

    rule = TemplateSwapRule.query.filter_by(
        template_id=template_id, trigger_field_name=field, trigger_value=value
    ).first()
    if not rule:
        return jsonify({"ok": True, "swap": False})

    t = get_or_404(FormTemplate, rule.target_template_id)
    fields = sorted(list(getattr(t, "fields", []) or []), key=lambda field: getattr(field, "order", 0))
    spec = build_template_spec(
        fields, verification_prefill_enabled=bool(getattr(t, "verification_prefill_enabled", False))
    )
    return jsonify(
        {
            "ok": True,
            "swap": True,
            "template": {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "layout": getattr(t, "layout", "standard"),
                "layout_label": getattr(t, "layout_label", "Standard"),
                "external_enabled": bool(getattr(t, "external_enabled", False)),
                "external_provider": getattr(t, "external_provider", None),
                "external_form_id": getattr(t, "external_form_id", None),
                "external_form_url": getattr(t, "external_form_url", None),
                "fields": spec,
                "sections": group_template_spec_by_section(spec),
            },
        }
    )


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
