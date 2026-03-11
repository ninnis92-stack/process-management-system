from __future__ import annotations


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
            pieces.append(
                f"{source} is one of {', '.join(str(v) for v in (rule.get('values') or []))}"
            )
        elif operator == "any_populated":
            pieces.append(f"section {source} has at least one populated field")
        elif operator == "all_populated":
            pieces.append(f"section {source} is fully populated")
    joiner = " and " if config.get("mode") == "all" else " or "
    if not pieces:
        return None
    return joiner.join(pieces)


def value_is_populated(value) -> bool:
    if value is None:
        return False
    if hasattr(value, "filename"):
        return bool(getattr(value, "filename", None))
    return str(value).strip() != ""


def evaluate_single_requirement_rule(
    rule, submission_data, verification_results, section_map
):
    source = rule.get("source")
    operator = rule.get("operator")
    source_type = rule.get("source_type")

    if source_type == "section":
        members = section_map.get(source, [])
        if operator == "any_populated":
            return any(
                value_is_populated(submission_data.get(name)) for name in members
            )
        if operator == "all_populated":
            return bool(members) and all(
                value_is_populated(submission_data.get(name)) for name in members
            )
        return False

    value = submission_data.get(source)
    if operator == "populated":
        return value_is_populated(value)
    if operator == "empty":
        return not value_is_populated(value)
    if operator == "verified":
        return (verification_results.get(source) or {}).get("ok") is True
    if operator == "equals":
        return str(value or "") == str(rule.get("value") or "")
    if operator == "not_equals":
        return str(value or "") != str(rule.get("value") or "")
    if operator == "one_of":
        return str(value or "") in {str(v) for v in (rule.get("values") or [])}
    return False


def evaluate_conditional_requirements(
    template_fields, submission_data, verification_results
):
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
            evaluate_single_requirement_rule(
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
