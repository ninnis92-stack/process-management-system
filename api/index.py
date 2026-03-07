from app import create_app
from flask import jsonify, request
from app.models import (
    FormTemplate,
    FormField,
    FormFieldOption,
    VerificationRule,
    IntegrationKey,
)
from app.extensions import db, get_or_404
from datetime import datetime

app = create_app()


def _check_api_key(req):
    key = (
        req.headers.get("X-Api-Key")
        or (req.headers.get("Authorization") or "").replace("Bearer ", "").strip()
    )
    if not key:
        return None
    ik = IntegrationKey.query.filter_by(key=key, active=True).first()
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
def api_template_verify(template_id: int):
    # Require API key for verification endpoints
    ik = _check_api_key(request)
    if not ik:
        return jsonify({"ok": False, "error": "auth_required"}), 401

    t = get_or_404(FormTemplate, template_id)
    data = request.get_json() or {}
    results = {}
    for f in t.fields:
        val = data.get(f.name)
        # default pass for empty optional
        results[f.name] = {"ok": True, "value": val}
        # apply simple verification rules (regex or external lookup can be configured later)
        if f.verification:
            try:
                # simple example: {'type':'regex','pattern':'^\d{4}$'}
                if f.verification.get("type") == "regex":
                    import re

                    pat = f.verification.get("pattern")
                    if pat and val is not None:
                        results[f.name]["ok"] = bool(re.match(pat, str(val)))
                    else:
                        results[f.name]["ok"] = False
                elif f.verification.get("type") == "external_lookup":
                    # external DB verification will be implemented by admin-configured params
                    # For now, mark as pending
                    results[f.name]["ok"] = False
                    results[f.name]["reason"] = "external_lookup_not_implemented"
            except Exception as e:
                results[f.name]["ok"] = False
                results[f.name]["error"] = str(e)

    return jsonify({"ok": True, "template_id": t.id, "results": results})
