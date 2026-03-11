from __future__ import annotations

import os
import time
import uuid
from collections import OrderedDict

from flask import current_app, request
from sqlalchemy import inspect as sa_inspect
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import Artifact, Attachment, FieldVerification
from ..models import Submission as FormSubmission
from .field_verification import (
    apply_prefill_values_to_submission,
    collect_prefill_target_names,
    extract_prefill_values,
    get_verification_prefill_config,
    normalize_bulk_separator,
    resolve_field_verification_rule,
    run_field_verification,
)
from .requirement_rules import (
    describe_requirement_rules,
    evaluate_conditional_requirements,
    normalize_requirement_rules,
    value_is_populated,
)


def group_template_spec_by_section(template_spec):
    grouped = OrderedDict()
    for field in template_spec or []:
        section_name = (field.get("section_name") or "Additional fields").strip()
        grouped.setdefault(section_name, []).append(field)
    return [
        {"name": section_name, "fields": fields}
        for section_name, fields in grouped.items()
    ]


def load_latest_field_verification_map(template_fields) -> dict[int, object]:
    latest_map: dict[int, object] = {}
    try:
        field_ids = [field.id for field in template_fields]
        if field_ids and sa_inspect(db.engine).has_table("field_verification"):
            rows = (
                db.session.query(FieldVerification)
                .filter(FieldVerification.field_id.in_(field_ids))
                .order_by(
                    FieldVerification.field_id.asc(),
                    FieldVerification.created_at.desc(),
                )
                .all()
            )
            for row in rows:
                if row.field_id not in latest_map:
                    latest_map[row.field_id] = row
    except Exception:
        latest_map = {}
    return latest_map


def build_template_spec(
    template_fields,
    latest_map: dict[int, object] | None = None,
    *,
    verification_prefill_enabled: bool = False,
):
    latest_map = latest_map or {}

    def _separator_label(separator):
        if separator == "\n":
            return "new line"
        if separator == "\t":
            return "tab"
        if separator == ",":
            return "comma"
        if separator == ";":
            return "semicolon"
        if separator == "|":
            return "pipe"
        return separator

    def _separator_token(separator):
        if separator == "\n":
            return "newline"
        if separator == "\t":
            return "tab"
        return separator

    spec = []
    for field in template_fields:
        options = [
            {
                "value": getattr(option, "value", None),
                "label": getattr(option, "value", None),
            }
            for option in (getattr(field, "options", []) or [])
        ]
        verification_rule = resolve_field_verification_rule(field, latest_map)
        field_hint = getattr(field, "hint", None)
        verification_meta = None
        if not field_hint and isinstance(verification_rule, dict):
            rule_params = verification_rule.get("params") or {}
            field_hint = rule_params.get("bulk_input_hint") or None
        if isinstance(verification_rule, dict):
            rule_params = verification_rule.get("params") or {}
            bulk_enabled = bool(rule_params.get("verify_each_separated_value", False))
            value_separator = normalize_bulk_separator(
                rule_params.get("value_separator") or rule_params.get("separator")
            )
            verification_meta = {
                "enabled": True,
                "provider": verification_rule.get("provider")
                or verification_rule.get("type"),
                "external_key": verification_rule.get("external_key")
                or verification_rule.get("key"),
                "bulk_enabled": bulk_enabled,
                "value_separator": value_separator,
                "value_separator_token": _separator_token(value_separator),
                "value_separator_label": _separator_label(value_separator),
                "camera_capture_mode": "append" if bulk_enabled else "replace",
                "prefill_enabled": False,
                "prefill_targets": [],
                "prefill_trigger": None,
            }
            if verification_prefill_enabled:
                prefill_cfg = get_verification_prefill_config(verification_rule)
                if prefill_cfg:
                    verification_meta.update(
                        {
                            "prefill_enabled": True,
                            "prefill_targets": list(
                                (prefill_cfg.get("targets") or {}).keys()
                            ),
                            "prefill_trigger": prefill_cfg.get("trigger") or "blur",
                        }
                    )
        spec.append(
            {
                "id": field.id,
                "name": getattr(field, "name", None),
                "label": getattr(field, "label", None),
                "field_type": getattr(field, "field_type", None),
                "required": bool(getattr(field, "required", False)),
                "section_name": getattr(field, "section_name", None),
                "hint": field_hint,
                "options": options,
                "verification": verification_meta,
                "requirements": {
                    "enabled": bool(
                        normalize_requirement_rules(
                            getattr(field, "requirement_rules", None)
                        )
                    ),
                    "summary": describe_requirement_rules(
                        getattr(field, "requirement_rules", None)
                    ),
                    # include full normalized configuration so client JS can
                    # evaluate rules and show dynamic hints
                    "config": normalize_requirement_rules(
                        getattr(field, "requirement_rules", None)
                    ),
                },
            }
        )
    return spec


def collect_template_submission_data(template_fields, skip_required_fields=None):
    skip_required_fields = set(skip_required_fields or [])
    submission_data = {}
    missing_field = None
    for field in template_fields:
        if getattr(field, "field_type", "") in ("file", "photo", "video"):
            value = request.files.get(field.name)
        else:
            value = request.form.get(field.name)

        if (
            field.required
            and field.name not in skip_required_fields
            and (
                value is None
                or (not getattr(value, "filename", None) and str(value).strip() == "")
            )
        ):
            missing_field = getattr(field, "label", field.name)
            break

        if getattr(field, "field_type", "") in ("file", "photo", "video"):
            submission_data[field.name] = (
                getattr(value, "filename", None) if value else None
            )
        else:
            submission_data[field.name] = value

    return submission_data, missing_field


def validate_required_template_submission(template_fields, submission_data: dict):
    for field in template_fields:
        value = submission_data.get(field.name)
        if field.required and (
            value is None
            or (not getattr(value, "filename", None) and str(value).strip() == "")
        ):
            return getattr(field, "label", field.name)
    return None


def validate_conditional_template_submission(
    template_fields,
    submission_data: dict,
    verification_results: dict | None = None,
):
    conditional_required = evaluate_conditional_requirements(
        template_fields, submission_data, verification_results or {}
    )
    for field in template_fields:
        if field.name not in conditional_required:
            continue
        value = submission_data.get(field.name)
        if not value_is_populated(value):
            return getattr(field, "label", field.name), conditional_required[field.name]
    return None, None


def get_template_prefill_target_names(
    template_fields,
    latest_map: dict[int, object] | None = None,
    *,
    enabled: bool = False,
) -> set[str]:
    if not enabled:
        return set()
    latest_map = latest_map or {}
    target_names: set[str] = set()
    for field in template_fields:
        rule = resolve_field_verification_rule(field, latest_map)
        if not rule:
            continue
        target_names.update(collect_prefill_target_names(rule))
    return target_names


def apply_submission_data_to_request(req, submission_data: dict):
    req.title = (
        submission_data.get("title")
        or submission_data.get("summary")
        or f"Dynamic request {int(time.time())}"
    )
    req.description = submission_data.get("description") or ""
    req.priority = submission_data.get("priority") or "medium"
    req.request_type = submission_data.get("request_type") or "both"
    req.pricebook_status = submission_data.get("pricebook_status") or "unknown"
    return req


def build_initial_artifact(
    req, form, submission_data: dict | None, current_user_id: int
):
    request_type = (req.request_type or "").strip()
    if request_type == "part_number":
        artifact_type = "part_number"
    elif request_type == "instructions":
        artifact_type = "instructions"
    else:
        artifact_type = "part_number"

    if submission_data is not None:
        instructions_url = submission_data.get("instructions_url")
        donor = submission_data.get("donor_part_number")
        target = submission_data.get("target_part_number")
        no_donor_reason = submission_data.get("no_donor_reason")
    else:
        instructions_field = getattr(form, "instructions_url", None)
        instructions_url = (
            (instructions_field.data or "").strip() if instructions_field else None
        )
        donor = (getattr(form, "donor_part_number", None).data or "").strip() or None
        target = (getattr(form, "target_part_number", None).data or "").strip() or None
        no_donor_reason = (
            getattr(form, "no_donor_reason", None).data or ""
        ).strip() or None

    return Artifact(
        request_id=req.id,
        instructions_url=instructions_url,
        artifact_type=artifact_type,
        donor_part_number=donor,
        target_part_number=target,
        no_donor_reason=no_donor_reason,
        created_by_user_id=current_user_id,
        created_by_department="A",
    )


def create_form_submission(template, req, submission_data: dict, current_user_id: int):
    form_submission = FormSubmission(
        template_id=template.id,
        request_id=req.id,
        data=submission_data,
        created_by_user_id=current_user_id,
    )
    db.session.add(form_submission)
    db.session.commit()
    return form_submission


def save_template_file_attachments(
    form_submission, template_fields, current_user_id: int
):
    # support generic file uploads as well as dedicated photo/video fields
    for field in template_fields:
        if field.field_type not in ("file", "photo", "video"):
            continue
        upload = request.files.get(field.name)
        if not (upload and upload.filename):
            continue

        filename = secure_filename(upload.filename)
        _, ext = os.path.splitext(filename)
        stored = f"uploads/{int(time.time())}-{uuid.uuid4().hex}{ext}"
        static_upload_dir = os.path.join(
            current_app.static_folder or "static", "uploads"
        )
        os.makedirs(static_upload_dir, exist_ok=True)
        destination = os.path.join(current_app.static_folder or "static", stored)
        upload.save(destination)

        attachment = Attachment(
            submission_id=form_submission.id,
            original_filename=filename,
            stored_filename=stored,
            content_type=upload.content_type or "application/octet-stream",
            size_bytes=os.path.getsize(destination),
            uploaded_by_user_id=current_user_id,
        )
        db.session.add(attachment)
        db.session.commit()


def run_template_field_verifications(
    template_fields,
    submission_data: dict,
    latest_map: dict[int, object] | None = None,
):
    verification_results = {}
    latest_map = latest_map or load_latest_field_verification_map(template_fields)

    for field in template_fields:
        rule = resolve_field_verification_rule(field, latest_map)
        if not rule:
            continue

        try:
            verification_results[field.name] = run_field_verification(
                field, rule, submission_data
            )
        except Exception as exc:
            current_app.logger.exception("Verification execution failed")
            verification_results[field.name] = {"ok": False, "error": str(exc)}

    return verification_results


def apply_template_verification_prefills(
    template_fields,
    submission_data: dict,
    verification_results: dict,
    latest_map: dict[int, object] | None = None,
    *,
    enabled: bool = False,
):
    if not enabled:
        return {}

    latest_map = latest_map or {}
    applied_by_source = {}
    for field in template_fields:
        rule = resolve_field_verification_rule(field, latest_map)
        if not rule:
            continue
        result = verification_results.get(field.name)
        prefills = extract_prefill_values(rule, result)
        if not prefills:
            continue
        applied = apply_prefill_values_to_submission(submission_data, prefills)
        if applied:
            applied_by_source[field.name] = applied
    return applied_by_source
