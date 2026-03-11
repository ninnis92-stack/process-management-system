from __future__ import annotations

from dataclasses import dataclass

from ..extensions import db
from ..models import DepartmentFormAssignment, FormTemplate
from .field_verification import (
    extract_prefill_values,
    get_verification_prefill_config,
    resolve_field_verification_rule,
    run_field_verification,
)
from .request_creation import (
    apply_template_verification_prefills,
    build_template_spec,
    collect_template_submission_data,
    get_template_prefill_target_names,
    group_template_spec_by_section,
    load_latest_field_verification_map,
    run_template_field_verifications,
    validate_conditional_template_submission,
    validate_required_template_submission,
)


@dataclass
class RequestTemplateContext:
    assigned: object | None
    template: object | None
    template_fields: list
    latest_map: dict
    template_spec: list | None
    template_sections: list | None


def load_request_template_context(department_name: str = "A") -> RequestTemplateContext:
    assigned = (
        DepartmentFormAssignment.query.filter_by(department_name=department_name)
        .order_by(DepartmentFormAssignment.created_at.desc())
        .first()
    )
    template = db.session.get(FormTemplate, assigned.template_id) if assigned else None
    template_fields = []
    latest_map = {}
    template_spec = None
    template_sections = None
    if template:
        template_fields = sorted(
            list(template.fields),
            key=lambda field: getattr(field, "created_at", getattr(field, "id", 0)),
        )
        if template_fields:
            latest_map = load_latest_field_verification_map(template_fields)
            template_spec = build_template_spec(
                template_fields,
                latest_map,
                verification_prefill_enabled=bool(
                    getattr(template, "verification_prefill_enabled", False)
                ),
            )
            template_sections = group_template_spec_by_section(template_spec)
    return RequestTemplateContext(
        assigned=assigned,
        template=template,
        template_fields=template_fields,
        latest_map=latest_map,
        template_spec=template_spec,
        template_sections=template_sections,
    )


def validate_template_request_submission(template_context: RequestTemplateContext):
    template = template_context.template
    template_fields = template_context.template_fields
    latest_map = template_context.latest_map

    prefill_target_names = get_template_prefill_target_names(
        template_fields,
        latest_map,
        enabled=bool(getattr(template, "verification_prefill_enabled", False)),
    )
    submission_data, missing_field = collect_template_submission_data(
        template_fields,
        skip_required_fields=prefill_target_names,
    )
    if missing_field:
        return {
            "ok": False,
            "error": "required_field_missing",
            "message": f"Field {missing_field} is required.",
            "submission_data": submission_data,
        }

    verification_results = run_template_field_verifications(
        template_fields, submission_data, latest_map
    )
    applied_prefills = apply_template_verification_prefills(
        template_fields,
        submission_data,
        verification_results,
        latest_map,
        enabled=bool(getattr(template, "verification_prefill_enabled", False)),
    )

    missing_field = validate_required_template_submission(
        template_fields, submission_data
    )
    if missing_field:
        return {
            "ok": False,
            "error": "required_field_missing_post_prefill",
            "message": f"Field {missing_field} is still required after verification and auto-fill.",
            "submission_data": submission_data,
            "verification_results": verification_results,
            "applied_prefills": applied_prefills,
        }

    conditional_missing_field, conditional_meta = (
        validate_conditional_template_submission(
            template_fields,
            submission_data,
            verification_results,
        )
    )
    if conditional_missing_field:
        return {
            "ok": False,
            "error": "conditional_requirement_missing",
            "message": conditional_meta.get("message")
            or f"Field {conditional_missing_field} is required by the current form rules.",
            "submission_data": submission_data,
            "verification_results": verification_results,
            "applied_prefills": applied_prefills,
            "conditional_meta": conditional_meta,
        }

    return {
        "ok": True,
        "submission_data": submission_data,
        "verification_results": verification_results,
        "applied_prefills": applied_prefills,
    }


def handle_template_prefill_request(
    template_context: RequestTemplateContext, payload: dict
):
    template = template_context.template
    if not template or not getattr(template, "verification_prefill_enabled", False):
        return {"ok": False, "error": "prefill_disabled"}, 400

    field_name = str(payload.get("field_name") or "").strip()
    values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
    if not field_name:
        return {"ok": False, "error": "missing_field_name"}, 400

    source_field = next(
        (
            field
            for field in template_context.template_fields
            if field.name == field_name
        ),
        None,
    )
    if not source_field:
        return {"ok": False, "error": "field_not_found"}, 404

    rule = resolve_field_verification_rule(source_field, template_context.latest_map)
    prefill_cfg = get_verification_prefill_config(rule)
    if not rule or not prefill_cfg:
        return {"ok": False, "error": "prefill_not_configured"}, 400

    if field_name not in values and payload.get("value") is not None:
        values[field_name] = payload.get("value")

    result = run_field_verification(source_field, rule, values)
    prefills = extract_prefill_values(rule, result)
    applied_prefills = {}
    for target_name, meta in prefills.items():
        if meta.get("overwrite") or values.get(target_name) in (None, ""):
            applied_prefills[target_name] = meta

    return {
        "ok": True,
        "result": result,
        "prefills": {
            key: value.get("value") for key, value in applied_prefills.items()
        },
        "meta": applied_prefills,
    }, 200
