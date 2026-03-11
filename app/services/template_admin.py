from __future__ import annotations

import json

from .requirement_rules import describe_requirement_rules, normalize_requirement_rules

DEFAULT_SECTION_NAME = "Ungrouped fields"


def update_template_field_settings(template, form_data, db_session):
    for field in template.fields:
        label = form_data.get(f"field_{field.id}_label")
        name = form_data.get(f"field_{field.id}_name")
        section = form_data.get(f"field_{field.id}_section")
        required = form_data.get(f"field_{field.id}_required")
        field_type = form_data.get(f"field_{field.id}_type")

        if label is not None:
            field.label = label.strip()
        if name is not None:
            field.name = name.strip() or field.name
        if section is not None:
            field.section_name = section.strip() or None
        if field_type is not None:
            field.field_type = field_type
        field.required = bool(required)
        db_session.add(field)

    template.verification_prefill_enabled = bool(
        form_data.get("verification_prefill_enabled")
    )
    # layout may be supplied when editing metadata; fall back to existing value
    if "layout" in form_data:
        template.layout = (form_data.get("layout") or "standard").strip() or "standard"
    template.external_enabled = bool(form_data.get("external_enabled"))
    template.external_provider = (
        form_data.get("external_provider") or ""
    ).strip() or None
    template.external_form_url = (
        form_data.get("external_form_url") or ""
    ).strip() or None
    template.external_form_id = (
        form_data.get("external_form_id") or ""
    ).strip() or None
    db_session.add(template)


def build_grouped_template_fields(fields):
    grouped_fields = []
    section_lookup = {}
    for field in fields:
        try:
            field.requirement_summary = describe_requirement_rules(
                getattr(field, "requirement_rules", None)
            )
        except Exception:
            field.requirement_summary = None
        section_name = (
            getattr(field, "section_name", None) or DEFAULT_SECTION_NAME
        ).strip() or DEFAULT_SECTION_NAME
        bucket = section_lookup.get(section_name)
        if bucket is None:
            bucket = {"name": section_name, "fields": []}
            section_lookup[section_name] = bucket
            grouped_fields.append(bucket)
        bucket["fields"].append(field)
    return grouped_fields


def build_requirement_editor_context(field):
    all_fields = [
        {"name": sibling.name, "label": sibling.label or sibling.name}
        for sibling in getattr(field.template, "fields", [])
        if sibling.id != field.id
    ]
    section_list = sorted(
        {
            (sibling.section_name or "").strip()
            for sibling in getattr(field.template, "fields", [])
            if (sibling.section_name or "").strip()
        }
    )
    return {"field_list": all_fields, "section_list": section_list}


def populate_requirement_form_from_rules(form, current_rules):
    if not isinstance(current_rules, dict):
        return
    form.enabled.data = bool(current_rules.get("enabled", False))
    form.scope.data = current_rules.get("scope") or "field"
    form.mode.data = current_rules.get("mode") or "all"
    form.message.data = current_rules.get("message") or ""
    try:
        form.rules_json.data = json.dumps(current_rules.get("rules") or [], indent=2)
    except Exception:
        form.rules_json.data = "[]"


def parse_requirement_rules_form(form):
    if not form.enabled.data:
        return None

    raw_rules = (form.rules_json.data or "").strip() or "[]"
    parsed_rules = json.loads(raw_rules)
    if not isinstance(parsed_rules, list):
        raise ValueError("Rules JSON must be a JSON array.")

    config = normalize_requirement_rules(
        {
            "enabled": True,
            "scope": form.scope.data or "field",
            "mode": form.mode.data or "all",
            "message": (form.message.data or "").strip() or None,
            "rules": parsed_rules,
        }
    )
    if form.enabled.data and not config:
        raise ValueError("At least one valid conditional rule is required.")
    return config
