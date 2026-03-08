from __future__ import annotations

import os
import time
import uuid
from collections import OrderedDict

from flask import current_app, request
from sqlalchemy import inspect as sa_inspect
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import (
    Artifact,
    Attachment,
    FieldVerification,
    Submission as FormSubmission,
)
from .field_verification import (
    apply_prefill_values_to_submission,
    collect_prefill_target_names,
    extract_prefill_values,
    get_verification_prefill_config,
    resolve_field_verification_rule,
    run_field_verification,
)


def normalize_requirement_rules(raw_rules) -> dict | None:
    if not isinstance(raw_rules, dict):
        return None

    enabled = bool(raw_rules.get("enabled"))
    rules = raw_rules.get("rules") or []
    if not enabled or not isinstance(rules, list) or not rules:
        return None

    mode = str(raw_rules.get("mode") or "all").strip().lower()
    if mode not in {"all", "any"}:
        mode = "all"

    scope = str(raw_rules.get("scope") or "field").strip().lower()
    if scope not in {"field", "section"}:
        scope = "field"

    normalized_rules = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        source_type = str(rule.get("source_type") or "field").strip().lower()
        if source_type not in {"field", "section"}:
            source_type = "field"
        source = str(rule.get("source") or "").strip()
        operator = str(rule.get("operator") or "populated").strip().lower()
        if not source:
            continue
        normalized_rule = {
            "source_type": source_type,
            "source": source,
            "operator": operator,
        }
        if "value" in rule:
            normalized_rule["value"] = rule.get("value")
        if "values" in rule and isinstance(rule.get("values"), list):
            normalized_rule["values"] = rule.get("values")
        normalized_rules.append(normalized_rule)

    if not normalized_rules:
        return None

    return {
        "enabled": True,
        "scope": scope,
        "mode": mode,
        "rules": normalized_rules,
        "message": (raw_rules.get("message") or "").strip() or None,
    }


def describe_requirement_rules(rules: dict | None) -> str | None:
    config = normalize_requirement_rules(rules)
    if not config:
        return None
    pieces = []
    for rule in config.get("rules") or []:
        source = rule.get("source")
        operator = rule.get("operator")
        if operator == "populated":
            pieces.append(f"{source} is filled in")
        elif operator == "empty":
            pieces.append(f"{source} is empty")
        elif operator == "verified":
            pieces.append(f"{source} verifies successfully")
        elif operator == "equals":
            pieces.append(f"{source} equals '{rule.get('value')}'")
        elif operator == "not_equals":
            pieces.append(f"{source} does not equal '{rule.get('value')}'")
        elif operator == "one_of":
            pieces.append(f"{source} is one of {', '.join(str(v) for v in (rule.get('values') or []))}")
        elif operator == "any_populated":
            pieces.append(f"section {source} has at least one populated field")
        elif operator == "all_populated":
            pieces.append(f"section {source} is fully populated")
    joiner = " and " if config.get("mode") == "all" else " or "
    if not pieces:
        return None
    return joiner.join(pieces)


def group_template_spec_by_section(template_spec):
    grouped = OrderedDict()
    for field in template_spec or []:
        section_name = (field.get("section_name") or "Additional fields").strip()
        grouped.setdefault(section_name, []).append(field)
    return [
        {"name": section_name, "fields": fields}
        for section_name, fields in grouped.items()
    ]


def _value_is_populated(value) -> bool:
    if value is None:
        return False
    if hasattr(value, "filename"):
        return bool(getattr(value, "filename", None))
    return str(value).strip() != ""


def _evaluate_single_requirement_rule(rule, submission_data, verification_results, section_map):
    source = rule.get("source")
    operator = rule.get("operator")
    source_type = rule.get("source_type")

    if source_type == "section":
        members = section_map.get(source, [])
        if operator == "any_populated":
            return any(_value_is_populated(submission_data.get(name)) for name in members)
        if operator == "all_populated":
            return bool(members) and all(
                _value_is_populated(submission_data.get(name)) for name in members
            )
        return False

    value = submission_data.get(source)
    if operator == "populated":
        return _value_is_populated(value)
    if operator == "empty":
        return not _value_is_populated(value)
    if operator == "verified":
        return (verification_results.get(source) or {}).get("ok") is True
    if operator == "equals":
        return str(value or "") == str(rule.get("value") or "")
    if operator == "not_equals":
        return str(value or "") != str(rule.get("value") or "")
    if operator == "one_of":
        return str(value or "") in {str(v) for v in (rule.get("values") or [])}
    return False


def evaluate_conditional_requirements(template_fields, submission_data, verification_results):
    section_map = {}
    for field in template_fields:
        section_name = (getattr(field, "section_name", None) or "").strip()
        if section_name:
            section_map.setdefault(section_name, []).append(field.name)

    required_targets = {}
    for field in template_fields:
        config = normalize_requirement_rules(getattr(field, "requirement_rules", None))
        if not config:
            continue
        results = [
            _evaluate_single_requirement_rule(
                rule, submission_data, verification_results or {}, section_map
            )
            for rule in (config.get("rules") or [])
        ]
        if not results:
            continue
        matched = all(results) if config.get("mode") == "all" else any(results)
        if not matched:
            continue
        if config.get("scope") == "section" and getattr(field, "section_name", None):
            targets = [
                f.name
                for f in template_fields
                if (getattr(f, "section_name", None) or "").strip()
                == (field.section_name or "").strip()
            ]
        else:
            targets = [field.name]
        for target in targets:
            required_targets[target] = {
                "message": config.get("message")
                or describe_requirement_rules(config)
                or "This field is conditionally required.",
                "scope": config.get("scope") or "field",
                "source_field": field.name,
            }
    return required_targets


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
            verification_meta = {
                "enabled": True,
                "provider": verification_rule.get("provider")
                or verification_rule.get("type"),
                "external_key": verification_rule.get("external_key")
                or verification_rule.get("key"),
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
                },
            }
        )
    return spec


def collect_template_submission_data(template_fields, skip_required_fields=None):
    skip_required_fields = set(skip_required_fields or [])
    submission_data = {}
    missing_field = None
    for field in template_fields:
        if getattr(field, "field_type", "") == "file":
            value = request.files.get(field.name)
        else:
            value = request.form.get(field.name)

        if field.required and field.name not in skip_required_fields and (
            value is None
            or (not getattr(value, "filename", None) and str(value).strip() == "")
        ):
            missing_field = getattr(field, "label", field.name)
            break

        if getattr(field, "field_type", "") == "file":
            submission_data[field.name] = getattr(value, "filename", None) if value else None
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
        if not _value_is_populated(value):
            return getattr(field, "label", field.name), conditional_required[field.name]
    return None, None


def get_template_prefill_target_names(
    template_fields, latest_map: dict[int, object] | None = None, *, enabled: bool = False
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


def build_initial_artifact(req, form, submission_data: dict | None, current_user_id: int):
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


def save_template_file_attachments(form_submission, template_fields, current_user_id: int):
    for field in template_fields:
        if field.field_type != "file":
            continue
        upload = request.files.get(field.name)
        if not (upload and upload.filename):
            continue

        filename = secure_filename(upload.filename)
        _, ext = os.path.splitext(filename)
        stored = f"uploads/{int(time.time())}-{uuid.uuid4().hex}{ext}"
        static_upload_dir = os.path.join(current_app.static_folder or "static", "uploads")
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