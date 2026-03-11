import os
import re
import time
from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, current_app, jsonify, request
from flask_wtf.csrf import generate_csrf

from app import csrf

from .. import notifcations as notifications
from ..extensions import db
from ..models import (
    PRIORITIES,
    REQUEST_TYPES,
    Artifact,
    DepartmentFormAssignment,
    EmailRouting,
    FormTemplate,
)
from ..models import Request as ReqModel
from ..models import SpecialEmailConfig, Submission, User
from ..security import rate_limit, verify_webhook_request
from ..services.inventory import InventoryService
from ..services.request_creation import (
    apply_submission_data_to_request,
    build_initial_artifact,
    build_template_spec,
    create_form_submission,
    group_template_spec_by_section,
)

integrations_bp = Blueprint("integrations_bp", __name__, url_prefix="/integrations")


def _get_latest_department_template(department_code: str):
    """Return the latest assigned form template for a department.

    This keeps inbound email validation aligned with whatever admins most
    recently assigned in the department form setup UI.
    """
    assigned = (
        DepartmentFormAssignment.query.filter_by(department_name=department_code)
        .order_by(DepartmentFormAssignment.created_at.desc())
        .first()
    )
    return db.session.get(FormTemplate, assigned.template_id) if assigned else None


def _get_shared_secret():
    # Prefer app config, then environment variable
    return current_app.config.get("WEBHOOK_SHARED_SECRET") or os.getenv(
        "WEBHOOK_SHARED_SECRET"
    )


def valid_hmac(payload: bytes, signature: str, secret: str) -> bool:
    ok, _reason = verify_webhook_request(
        payload=payload,
        signature=signature,
        secret=secret,
        timestamp=request.headers.get("X-Webhook-Timestamp"),
    )
    return ok


@integrations_bp.route("/templates/<int:template_id>/external-schema", methods=["GET"])
@rate_limit("external_schema", config_key="WEBHOOK_RATE_LIMIT", default="60/60")
def external_form_schema(template_id: int):
    """Expose a generated schema for connected third-party form builders."""
    template = db.session.get(FormTemplate, template_id)
    if not template or not getattr(template, "external_enabled", False):
        return jsonify({"ok": False, "error": "template_not_external"}), 404

    fields = sorted(
        list(getattr(template, "fields", []) or []),
        key=lambda field: getattr(field, "order", 0),
    )
    spec = build_template_spec(
        fields,
        verification_prefill_enabled=bool(
            getattr(template, "verification_prefill_enabled", False)
        ),
    )
    return jsonify(
        {
            "ok": True,
            "template": {
                "id": template.id,
                "name": template.name,
                "description": template.description,
                "layout": getattr(template, "layout", "standard"),
                "layout_label": getattr(template, "layout_label", "Standard"),
                "external_provider": getattr(template, "external_provider", None),
                "external_form_id": getattr(template, "external_form_id", None),
                "external_form_url": getattr(template, "external_form_url", None),
                "fields": spec,
                "sections": group_template_spec_by_section(spec),
            },
        }
    )


@integrations_bp.route("/incoming-webhook", methods=["POST"])
@csrf.exempt
@rate_limit("incoming_webhook", config_key="WEBHOOK_RATE_LIMIT", default="60/60")
def incoming_webhook():
    """Accepts external POSTs from third-party services.

    This route is intentionally CSRF-exempt; callers MUST present a valid
    HMAC signature in the `X-Webhook-Signature` header. The shared secret is
    looked up from `WEBHOOK_SHARED_SECRET` in app config or env.
    """
    payload = request.get_data() or b""
    sig = request.headers.get("X-Webhook-Signature") or request.headers.get(
        "X-Signature"
    )
    timestamp = request.headers.get("X-Webhook-Timestamp")
    secret = _get_shared_secret()
    if not secret:
        current_app.logger.warning(
            "Incoming webhook rejected: no shared secret configured"
        )
        abort(401)

    ok, reason = verify_webhook_request(
        payload=payload,
        signature=sig,
        secret=secret,
        timestamp=timestamp,
    )
    if not ok:
        current_app.logger.warning("Incoming webhook rejected: %s", reason)
        abort(401)

    # At this point the webhook is authenticated. Implement service-specific
    # payload parsing and processing here. Keep processing short or enqueue a
    # background job.
    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}

    # example: log and return 204
    current_app.logger.info(
        "Received webhook: %s",
        {"headers": dict(request.headers), "json_keys": list(data.keys())},
    )
    return ("", 204)


@integrations_bp.route("/external-form-callback", methods=["POST"])
@csrf.exempt
@rate_limit("external_form_callback", config_key="WEBHOOK_RATE_LIMIT", default="60/60")
def external_form_callback():
    """Accept callbacks from external form providers (e.g. Microsoft Forms).

    Expected JSON payload examples:
      {
        "external_form_id": "abcd-1234",             # optional
        "template_id": 12,                            # optional fallback
        "form_response": { "title": "...", ... }  # mapping of field keys to values
      }

    The endpoint verifies the same HMAC-based header as other webhooks
    and will try to locate a `FormTemplate` by `external_form_id` or
    by `template_id`. If found and `external_enabled` is True, a new
    `Request` will be created and a `Submission` row will be stored
    with the raw data.
    """
    payload = request.get_data() or b""
    sig = request.headers.get("X-Webhook-Signature") or request.headers.get(
        "X-Signature"
    )
    timestamp = request.headers.get("X-Webhook-Timestamp")
    secret = _get_shared_secret()
    ok, reason = verify_webhook_request(
        payload=payload,
        signature=sig,
        secret=secret,
        timestamp=timestamp,
    )
    if not secret or not ok:
        current_app.logger.warning(
            "External form callback rejected: %s",
            reason or "invalid/no signature",
        )
        abort(401)

    data = request.get_json(silent=True) or {}
    # Allow provider-specific payloads to be normalized.
    form_data = data.get("form_response") or data.get("data") or {}

    # If template indicates a provider, allow special parsing
    def _normalize_provider_payload(provider, raw):
        if not provider or not isinstance(raw, dict):
            return raw
        p = (provider or "").strip().lower()
        # Microsoft Forms: attempt to map answers into key->value pairs
        if p in ("microsoft_forms", "microsoft"):
            # Example Microsoft Forms callback may include `response` -> `answers` list
            # where each answer has `question` and `answer` or similar keys.
            try:
                if "response" in raw and isinstance(raw.get("response"), dict):
                    resp = raw.get("response")
                    answers = resp.get("answers") or resp.get("items") or []
                    out = {}
                    # Try common shapes
                    for a in answers:
                        if isinstance(a, dict):
                            # prefer explicit name keys
                            key = a.get("question") or a.get("name") or a.get("id")
                            val = a.get("answer") or a.get("value") or a.get("text")
                            if key:
                                out[str(key)] = val
                    # Fallback: top-level fields
                    for k, v in raw.items():
                        if k not in ("response", "answers", "items") and not out.get(k):
                            out[k] = v
                    return out
            except Exception:
                current_app.logger.exception("Failed parsing Microsoft Forms payload")
        return raw

    external_form_id = (data.get("external_form_id") or "").strip() or None
    template = None
    try:
        if external_form_id:
            template = FormTemplate.query.filter_by(
                external_form_id=external_form_id
            ).first()
        if not template and data.get("template_id"):
            try:
                tid = int(data.get("template_id"))
                template = db.session.get(FormTemplate, tid)
            except Exception:
                template = None
    except Exception:
        current_app.logger.exception(
            "Failed locating FormTemplate for external callback"
        )

    if not template:
        current_app.logger.warning("External form callback: no matching template")
        return jsonify({"ok": False, "error": "no_template"}), 400

    if not getattr(template, "external_enabled", False):
        current_app.logger.warning(
            "External form callback received for template without external_enabled"
        )
        return jsonify({"ok": False, "error": "template_not_external"}), 400
    # Normalize provider-specific payloads when provider is set on the template
    provider = getattr(template, "external_provider", None)
    form_data = _normalize_provider_payload(provider, form_data or {})

    # Attempt to map incoming form keys to template `FormField`s so external
    # submissions can be translated into the same field names used by the
    # native in-app form.
    def _attempt_field_mapping(template, payload):
        """Return (mapped_values, mapped_keys) where mapped_values maps
        field.id -> value and mapped_keys maps field.id -> payload key used.
        This stores the mapping into the submission `data` under the
        reserved `_field_map` key when at least one mapping is found.
        """
        mapped_values = {}
        mapped_keys = {}
        try:
            if not template or not isinstance(payload, dict):
                return mapped_values, mapped_keys

            # Build candidate lookup map: normalize payload keys to ease matching
            def norm(s):
                return (
                    (s or "")
                    .strip()
                    .lower()
                    .replace("\n", " ")
                    .replace("_", " ")
                    .replace("-", " ")
                )

            key_map = {}
            for k, v in payload.items():
                key_map[norm(str(k))] = (k, v)

            for field in getattr(template, "fields", []) or []:
                fname = (getattr(field, "name", "") or "").strip()
                flabel = (getattr(field, "label", "") or "").strip()
                candidates = [fname, flabel]
                # allow JSON verification mapping if present
                try:
                    verification = getattr(field, "verification", None) or {}
                    if isinstance(verification, dict) and verification.get(
                        "external_key"
                    ):
                        candidates.append(str(verification.get("external_key")))
                except Exception:
                    pass

                found = False
                for c in candidates:
                    if not c:
                        continue
                    nk = norm(c)
                    if nk in key_map:
                        orig_key, val = key_map[nk]
                        mapped_values[field.id] = val
                        mapped_keys[field.id] = orig_key
                        found = True
                        break

                # Last resort: direct exact key match
                if not found and fname and fname in payload:
                    mapped_values[field.id] = payload.get(fname)
                    mapped_keys[field.id] = fname
        except Exception:
            current_app.logger.exception("Field mapping attempt failed")

        return mapped_values, mapped_keys

    def _normalize_native_submission_data(template, payload):
        """Translate third-party payloads into native template field names."""
        translated = dict(payload or {})
        mapped_values, mapped_keys = _attempt_field_mapping(template, payload or {})
        translated["_native_translation"] = {
            "template_id": getattr(template, "id", None),
            "template_name": getattr(template, "name", None),
            "layout": getattr(template, "layout", "standard"),
            "external_provider": getattr(template, "external_provider", None),
        }
        if not mapped_values:
            return translated

        translated_field_map = {}
        for field in getattr(template, "fields", []) or []:
            if field.id not in mapped_values:
                continue
            target_name = (getattr(field, "name", None) or "").strip()
            if not target_name:
                continue
            translated[target_name] = mapped_values[field.id]
            translated_field_map[target_name] = {
                "field_id": field.id,
                "payload_key": mapped_keys.get(field.id),
                "value": mapped_values[field.id],
            }
        if translated_field_map:
            translated["_field_map"] = translated_field_map
            translated["_mapped"] = True
        return translated

    form_data = _normalize_native_submission_data(template, form_data or {})

    title = (
        form_data.get("title")
        or form_data.get("summary")
        or f"External submission {int(time.time())}"
    )
    description = form_data.get("description") or form_data.get("details") or ""
    priority = form_data.get("priority") or "medium"
    request_type = form_data.get("request_type") or "both"
    pricebook_status = (
        form_data.get("pricebook_status") or form_data.get("sales_list") or "unknown"
    )
    due_at = None
    raw_due = (form_data.get("due_at") or form_data.get("due") or "").strip()
    if raw_due:
        try:
            from datetime import datetime

            due_at = datetime.fromisoformat(raw_due.replace("Z", "+00:00"))
            if getattr(due_at, "tzinfo", None) is not None:
                due_at = due_at.astimezone(tz=None).replace(tzinfo=None)
        except Exception:
            due_at = None

    # determine owner department via DepartmentFormAssignment mapping for this template
    owner_dept = "B"
    try:
        assign = (
            DepartmentFormAssignment.query.filter_by(template_id=template.id)
            .order_by(DepartmentFormAssignment.created_at.desc())
            .first()
        )
        if assign and assign.department_name:
            owner_dept = assign.department_name.strip().upper()
    except Exception:
        current_app.logger.exception(
            "Failed resolving DepartmentFormAssignment for external submission"
        )

    created_request_id = None
    try:
        req = ReqModel(
            title=title,
            request_type=(request_type if request_type in REQUEST_TYPES else "both"),
            pricebook_status=(
                pricebook_status
                if pricebook_status in ("in_pricebook", "not_in_pricebook", "unknown")
                else "unknown"
            ),
            description=description,
            priority=(priority if priority in PRIORITIES else "medium"),
            status="NEW_FROM_A",
            owner_department=owner_dept,
            submitter_type="guest",
            due_at=(due_at or (datetime.utcnow() + timedelta(days=2))),
        )
        db.session.add(req)
        db.session.flush()

        # Reuse the native request population logic so external callbacks behave
        # like the internal dynamic form whenever compatible fields are present.
        apply_submission_data_to_request(req, form_data)

        try:
            artifact = build_initial_artifact(req, None, form_data, None)
            artifact.created_by_department = owner_dept or "B"
            artifact.created_by_guest_email = (
                form_data.get("guest_email") if isinstance(form_data, dict) else None
            )
            has_artifact_payload = bool(
                artifact.instructions_url
                or artifact.donor_part_number
                or artifact.target_part_number
                or artifact.no_donor_reason
            )
            if has_artifact_payload:
                db.session.add(artifact)
        except Exception:
            current_app.logger.exception(
                "Failed creating artifacts from external form data"
            )

        form_submission = create_form_submission(template, req, form_data, None)
        form_submission.from_department = None
        form_submission.to_department = owner_dept
        form_submission.summary = (
            form_data.get("summary") or form_data.get("title") or None
        )
        form_submission.details = description
        form_submission.created_by_guest_email = (
            form_data.get("guest_email") if isinstance(form_data, dict) else None
        )
        db.session.commit()
        created_request_id = req.id
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Failed creating Request/Submission from external form"
        )

    current_app.logger.info(
        "External form callback processed",
        extra={"template_id": template.id, "created_request_id": created_request_id},
    )
    return jsonify({"ok": True, "created_request_id": created_request_id})


@integrations_bp.route("/inbound-mail", methods=["POST"])
@csrf.exempt
def inbound_mail():
    """Inbound mail webhook for mail providers (prototype).

    Expected fields (JSON or form):
      - from: sender email
      - to: destination email
      - subject: subject line
      - body: plaintext body

    The endpoint verifies the shared HMAC signature like other webhooks.
    If the configured Request Form feature is enabled, an autoresponder
    will be queued and the subject will be parsed into a key/value map
    using semicolon-separated `key=value` pairs. Inventory checks are
    performed via `InventoryService` where applicable. This handler is
    safe to call even when no inventory connector is configured.
    """
    payload = request.get_data() or b""
    sig = request.headers.get("X-Webhook-Signature") or request.headers.get(
        "X-Signature"
    )
    secret = _get_shared_secret()
    if not secret or not valid_hmac(payload, sig, secret):
        current_app.logger.warning("Inbound mail rejected: invalid/no signature")
        abort(401)

    # Accept JSON or form-encoded payloads
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    sender = (data.get("from") or data.get("sender") or "").strip()
    recipient = (data.get("to") or "").strip().lower()
    subject = (data.get("subject") or "").strip()
    body = (data.get("body") or data.get("text") or "").strip()

    if not sender:
        current_app.logger.warning("Inbound mail missing sender")
        return (jsonify({"ok": False, "error": "missing_sender"}), 400)

    cfg = SpecialEmailConfig.get()

    # Optional mailbox routing guard: resolve explicit request_form_email first,
    # then fall back to configured SSO owner email when available.
    target = None
    if getattr(cfg, "request_form_email", None):
        target = cfg.request_form_email.strip().lower()
    else:
        try:
            owner_id = int(getattr(cfg, "request_form_user_id", 0) or 0)
        except Exception:
            owner_id = 0
        if owner_id:
            owner_user = db.session.get(User, owner_id)
            if owner_user and owner_user.email:
                target = owner_user.email.strip().lower()

    if target:
        if recipient and target not in recipient:
            return jsonify({"ok": True, "skipped": "recipient_mismatch"})

    sent = False

    # Parse subject into key/value pairs for potential request creation
    parsed = {}
    if subject:
        # Expect format: key1=val1;key2=val2;...
        parts = [p.strip() for p in subject.split(";") if p.strip()]
        for p in parts:
            if "=" in p:
                k, v = p.split("=", 1)
                parsed[k.strip()] = v.strip()

    # Inventory validation for donor/target/price_book_number if present
    inv = InventoryService()
    checks = {}
    for key in ("donor_part_number", "target_part_number", "price_book_number"):
        if parsed.get(key):
            try:
                ok = None
                if key in ("donor_part_number", "target_part_number"):
                    ok = inv.validate_part_number(parsed.get(key))
                else:
                    ok = inv.validate_sales_list_number(parsed.get(key))
                if ok is True:
                    checks[key] = True
                elif ok is False:
                    checks[key] = False
                else:
                    checks[key] = None
            except Exception:
                checks[key] = False

    created_request_id = None
    validation_rejected = False
    invalid_fields = []
    out_of_stock_fields = []
    out_of_stock_notified = False
    out_of_stock_notify_mode = None
    if cfg.enabled:
        try:
            sender_norm = sender.lower().strip()
            user = User.query.filter_by(email=sender_norm).first()
            recognized_sso = bool(user and user.sso_sub)

            if recognized_sso:
                desired_dept = (cfg.request_form_department or "A").upper().strip()
                if desired_dept not in ("A", "B", "C"):
                    desired_dept = "A"
                if user.department != desired_dept:
                    user.department = desired_dept

            req_type_raw = (parsed.get("request_type") or "").strip().lower()
            req_type = req_type_raw or "both"
            if req_type_raw and req_type_raw not in REQUEST_TYPES:
                invalid_fields.append("request_type")
            if req_type not in REQUEST_TYPES:
                req_type = "both"

            prio_raw = (parsed.get("priority") or "").strip().lower()
            prio = prio_raw or "medium"
            if prio_raw and prio_raw not in PRIORITIES:
                invalid_fields.append("priority")
            if prio not in PRIORITIES:
                prio = "medium"

            sales_list_raw = (
                (parsed.get("sales_list") or parsed.get("pricebook_status") or "")
                .strip()
                .lower()
            )
            sales_list = sales_list_raw or "unknown"
            if sales_list_raw and sales_list_raw not in (
                "in_pricebook",
                "not_in_pricebook",
                "unknown",
            ):
                invalid_fields.append("sales_list")
            if sales_list not in ("in_pricebook", "not_in_pricebook", "unknown"):
                sales_list = "unknown"

            due_at = None
            raw_due = (parsed.get("due_at") or "").strip()
            if raw_due:
                try:
                    due_dt = datetime.fromisoformat(raw_due.replace("Z", "+00:00"))
                    if due_dt.tzinfo is not None:
                        due_dt = due_dt.astimezone(timezone.utc).replace(tzinfo=None)
                    due_at = due_dt
                except Exception:
                    due_at = None
                    invalid_fields.append("due_at")
            if due_at is None:
                due_at = datetime.utcnow() + timedelta(days=2)

            for field_name, is_valid in checks.items():
                if parsed.get(field_name) and is_valid is False:
                    invalid_fields.append(field_name)

            # Verify against admin-edited department form fields when strict mode is enabled.
            strict_validation = bool(
                getattr(cfg, "request_form_field_validation_enabled", False)
            )
            dept = (getattr(cfg, "request_form_department", "A") or "A").strip().upper()
            if strict_validation and dept in ("A", "B", "C"):
                try:
                    # Validation contract:
                    # - required fields must be present
                    # - select/radio values must be one of configured options
                    # - regex validators must match when configured on the field
                    template = _get_latest_department_template(dept)
                    if template:
                        template_fields = sorted(
                            list(getattr(template, "fields", []) or []),
                            key=lambda f: getattr(f, "created_at", getattr(f, "id", 0)),
                        )
                        for field in template_fields:
                            field_name = (getattr(field, "name", "") or "").strip()
                            if not field_name:
                                continue
                            field_type = (
                                (getattr(field, "field_type", "") or "").strip().lower()
                            )
                            if field_type == "file":
                                continue

                            value = (parsed.get(field_name) or "").strip()
                            is_required = bool(getattr(field, "required", False))
                            if is_required and not value:
                                invalid_fields.append(field_name)
                                continue
                            if not value:
                                continue

                            options = [
                                str(getattr(o, "value", "")).strip()
                                for o in (getattr(field, "options", []) or [])
                                if str(getattr(o, "value", "")).strip()
                            ]
                            if options and value not in options:
                                invalid_fields.append(field_name)
                                continue

                            verification = getattr(field, "verification", None) or {}
                            if (
                                isinstance(verification, dict)
                                and verification.get("type") == "regex"
                                and verification.get("pattern")
                            ):
                                pattern = str(verification.get("pattern"))
                                if not re.match(pattern, value or ""):
                                    invalid_fields.append(field_name)
                except Exception:
                    current_app.logger.exception(
                        "Failed to verify inbound fields against assigned department form template"
                    )

            out_of_stock_fields = [
                field_name
                for field_name, is_valid in checks.items()
                if parsed.get(field_name) and is_valid is False
            ]
            notify_on_out_of_stock = bool(
                getattr(
                    cfg, "request_form_inventory_out_of_stock_notify_enabled", False
                )
            )
            if notify_on_out_of_stock and out_of_stock_fields:
                out_of_stock_notify_mode = (
                    (
                        getattr(
                            cfg,
                            "request_form_inventory_out_of_stock_notify_mode",
                            "email",
                        )
                        or "email"
                    )
                    .strip()
                    .lower()
                )
                if out_of_stock_notify_mode not in ("notification", "email", "both"):
                    out_of_stock_notify_mode = "email"
                out_of_stock_message = getattr(
                    cfg, "request_form_inventory_out_of_stock_message", None
                )
                bullet_list = "\n".join([f"- {f}" for f in out_of_stock_fields])
                message_text = (
                    out_of_stock_message.replace("{out_of_stock_fields}", bullet_list)
                    if out_of_stock_message
                    and isinstance(out_of_stock_message, str)
                    and out_of_stock_message.strip()
                    else (
                        "Your request-by-email submission includes inventory fields that are currently out of stock.\n\n"
                        "Out-of-stock field(s):\n"
                        f"{bullet_list}\n\n"
                        "You can continue by updating the parts/values, or wait for inventory restock."
                    )
                )
                try:
                    did_notify = False
                    if (
                        out_of_stock_notify_mode in ("notification", "both")
                        and user is not None
                    ):
                        notifications.notify_users(
                            [user],
                            title="Inventory out-of-stock notice",
                            body=message_text,
                            ntype="inventory_out_of_stock",
                            request_id=None,
                            allow_email=False,
                        )
                        db.session.commit()
                        did_notify = True

                    if out_of_stock_notify_mode in ("email", "both"):
                        email_sent = notifications.send_request_form_inventory_out_of_stock_notice(
                            sender,
                            out_of_stock_fields,
                            message=out_of_stock_message,
                        )
                        did_notify = bool(did_notify or email_sent)

                    out_of_stock_notified = bool(did_notify)
                except Exception:
                    db.session.rollback()
                    out_of_stock_notified = False
                    current_app.logger.exception(
                        "Failed to send inbound out-of-stock notification email"
                    )

            # Preserve order while removing duplicates
            invalid_fields = list(dict.fromkeys(invalid_fields))
            if strict_validation and invalid_fields:
                validation_rejected = True
                try:
                    notifications.send_request_form_validation_rejection(
                        sender, invalid_fields
                    )
                except Exception:
                    current_app.logger.exception(
                        "Failed to send inbound validation rejection email"
                    )
                return jsonify(
                    {
                        "ok": True,
                        "autoresponder_sent": False,
                        "rejected": True,
                        "invalid_fields": invalid_fields,
                        "out_of_stock_notified": bool(out_of_stock_notified),
                        "out_of_stock_fields": out_of_stock_fields,
                        "out_of_stock_notify_mode": out_of_stock_notify_mode,
                        "parsed": parsed,
                        "checks": checks,
                        "created_request_id": None,
                    }
                )

            # Queue autoresponder only when strict validation does not reject the submission.
            try:
                sent = notifications.send_request_form_autoresponder(sender)
            except Exception:
                sent = False

            title = (
                parsed.get("title") or ""
            ).strip() or f"Email request from {sender}"
            description = (
                (parsed.get("description") or "").strip()
                or body
                or "Submitted via inbound email."
            )

            # Determine owner department using admin-defined EmailRouting when present.
            owner_dept = "B"
            try:
                mappings = EmailRouting.for_recipient(recipient)
            except Exception:
                mappings = []

            if mappings:
                mapped_codes = [
                    (m.department_code or "").upper().strip()
                    for m in mappings
                    if m.department_code
                ]
                # If the sender is a recognized SSO user and their department is
                # allowed for this recipient, prefer it; otherwise pick the first
                # mapped department as the owner.
                if (
                    recognized_sso
                    and user
                    and getattr(user, "department", None)
                    and user.department.upper() in mapped_codes
                ):
                    owner_dept = user.department.upper()
                else:
                    owner_dept = mapped_codes[0] if mapped_codes else owner_dept
            else:
                # Fallback to configured request form department or B
                owner_dept = (
                    (getattr(cfg, "request_form_department", "B") or "B")
                    .strip()
                    .upper()
                )

            req = ReqModel(
                title=title,
                request_type=req_type,
                pricebook_status=sales_list,
                sales_list_reference=(parsed.get("price_book_number") or "").strip()
                or None,
                description=description,
                priority=prio,
                status="NEW_FROM_A",
                owner_department=owner_dept,
                submitter_type="user" if recognized_sso else "guest",
                created_by_user_id=(user.id if recognized_sso else None),
                guest_email=(None if recognized_sso else sender_norm),
                guest_name=(None if recognized_sso else sender.split("@")[0]),
                due_at=due_at,
            )
            # capture original sender if admin requested
            if getattr(cfg, "request_form_add_original_sender", False):
                req.original_sender = sender_norm

            if not recognized_sso:
                req.ensure_guest_token()

            db.session.add(req)
            db.session.commit()
            created_request_id = req.id

            # apply default watchers and notify them with a quick link
            watchers = []
            if getattr(cfg, "request_form_default_watchers", None):
                try:
                    watchers = [
                        e.strip().lower()
                        for e in getattr(cfg, "request_form_default_watchers") or []
                        if e and e.strip()
                    ]
                except Exception:
                    watchers = []
            # optionally treat original sender itself as a watcher
            if getattr(cfg, "request_form_add_original_sender", False) and sender_norm:
                if sender_norm not in watchers:
                    watchers.append(sender_norm)
            if watchers:
                req.watcher_emails = watchers
                db.session.add(req)
                db.session.commit()
                try:
                    notifications.send_request_link_email(watchers, req)
                except Exception:
                    current_app.logger.exception("Failed to notify watchers")
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Failed to create request from inbound mail")

    current_app.logger.info(
        "Inbound mail processed",
        extra={
            "from": sender,
            "subject": subject,
            "parsed_keys": list(parsed.keys()),
            "checks": checks,
            "autoresponder_sent": bool(sent),
            "validation_rejected": validation_rejected,
            "invalid_fields": invalid_fields,
            "out_of_stock_notified": bool(out_of_stock_notified),
            "out_of_stock_fields": out_of_stock_fields,
            "out_of_stock_notify_mode": out_of_stock_notify_mode,
            "created_request_id": created_request_id,
        },
    )

    return jsonify(
        {
            "ok": True,
            "autoresponder_sent": bool(sent),
            "rejected": bool(validation_rejected),
            "invalid_fields": invalid_fields,
            "out_of_stock_notified": bool(out_of_stock_notified),
            "out_of_stock_fields": out_of_stock_fields,
            "out_of_stock_notify_mode": out_of_stock_notify_mode,
            "parsed": parsed,
            "checks": checks,
            "created_request_id": created_request_id,
        }
    )


@integrations_bp.route("/csrf-token", methods=["GET"])
def csrf_token():
    """Return a fresh CSRF token for API clients.

    Clients should GET this endpoint (it will set the session cookie) and then
    include the token value in the `X-CSRFToken` header for subsequent POSTs.
    """
    token = generate_csrf()
    return jsonify({"csrf_token": token})
