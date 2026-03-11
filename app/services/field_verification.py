from __future__ import annotations

from typing import Any, Dict

from ..models import FormField
from .inventory import InventoryService
from .verification import VerificationService


def resolve_field_verification_rule(field: FormField, latest_map: Dict[int, object]):
    inline = getattr(field, "verification", None)
    if inline:
        return inline

    mapped = latest_map.get(getattr(field, "id", None))
    if not mapped:
        return None

    return {
        "provider": getattr(mapped, "provider", None),
        "external_key": getattr(mapped, "external_key", None),
        "params": getattr(mapped, "params", None) or {},
        "triggers_auto_reject": bool(getattr(mapped, "triggers_auto_reject", False)),
        "type": "external_lookup",
    }


def normalize_bulk_separator(raw_value):
    raw = str(raw_value or "").strip()
    if not raw:
        return ","
    aliases = {
        "comma": ",",
        "semicolon": ";",
        "pipe": "|",
        "newline": "\n",
        "\\n": "\n",
        "tab": "\t",
        "\\t": "\t",
    }
    return aliases.get(raw.lower(), raw)


def apply_bulk_verification_params(
    params: Dict[str, Any] | None,
    *,
    verify_each_separated_value: bool,
    value_separator: str | None,
    bulk_input_hint: str | None,
) -> Dict[str, Any]:
    merged = dict(params or {})
    merged["verify_each_separated_value"] = bool(verify_each_separated_value)
    merged["value_separator"] = normalize_bulk_separator(value_separator)

    if (bulk_input_hint or "").strip():
        merged["bulk_input_hint"] = bulk_input_hint.strip()
    else:
        merged.pop("bulk_input_hint", None)

    return merged


def _prefill_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def collect_prefill_target_names(rule) -> set[str]:
    config = get_verification_prefill_config(rule)
    if not config:
        return set()
    return set(config.get("targets", {}).keys())


def get_verification_prefill_config(rule) -> Dict[str, Any] | None:
    if not isinstance(rule, dict):
        return None

    params = rule.get("params") or {}
    if not _prefill_bool(params.get("prefill_enabled")):
        return None

    raw_targets = params.get("prefill_targets") or params.get("linked_fields") or {}
    if not isinstance(raw_targets, dict) or not raw_targets:
        return None

    default_overwrite = _prefill_bool(params.get("prefill_overwrite_existing"))
    trigger = (params.get("prefill_trigger") or "blur").strip().lower() or "blur"
    targets: Dict[str, Dict[str, Any]] = {}

    for field_name, target_spec in raw_targets.items():
        if not isinstance(field_name, str) or not field_name.strip():
            continue
        if isinstance(target_spec, str):
            path = target_spec.strip()
            overwrite = default_overwrite
        elif isinstance(target_spec, dict):
            path = str(
                target_spec.get("path") or target_spec.get("source") or ""
            ).strip()
            overwrite = _prefill_bool(target_spec.get("overwrite", default_overwrite))
        else:
            continue
        if not path:
            continue
        targets[field_name.strip()] = {
            "path": path,
            "overwrite": overwrite,
        }

    if not targets:
        return None

    return {
        "enabled": True,
        "trigger": trigger,
        "overwrite_existing": default_overwrite,
        "targets": targets,
    }


def _get_prefill_path_value(result: Dict[str, Any], path: str):
    parts = [segment for segment in str(path or "").split(".") if segment]
    if not parts:
        return None

    if parts[0] == "result":
        current = result
        parts = parts[1:]
    elif parts[0] == "details":
        current = result.get("details") if isinstance(result, dict) else None
        parts = parts[1:]
    else:
        current = result

    if not parts:
        return current

    for idx, part in enumerate(parts):
        if isinstance(current, dict) and part in current:
            current = current.get(part)
            continue
        if (
            idx == 0
            and isinstance(result, dict)
            and isinstance(result.get("details"), dict)
            and part in (result.get("details") or {})
        ):
            current = result.get("details", {}).get(part)
            continue
        return None
    return current


def extract_prefill_values(
    rule, result: Dict[str, Any] | None
) -> Dict[str, Dict[str, Any]]:
    config = get_verification_prefill_config(rule)
    if not config or not isinstance(result, dict) or result.get("ok") is not True:
        return {}

    prefills: Dict[str, Dict[str, Any]] = {}
    for field_name, target_spec in (config.get("targets") or {}).items():
        value = _get_prefill_path_value(result, target_spec.get("path"))
        if value is None or isinstance(value, (dict, list, tuple, set)):
            continue
        prefills[field_name] = {
            "value": value,
            "path": target_spec.get("path"),
            "overwrite": bool(target_spec.get("overwrite", False)),
        }
    return prefills


def apply_prefill_values_to_submission(
    submission_data: Dict[str, Any], prefills: Dict[str, Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    applied: Dict[str, Dict[str, Any]] = {}
    for field_name, payload in (prefills or {}).items():
        existing = submission_data.get(field_name)
        if existing not in (None, "") and not payload.get("overwrite"):
            continue
        submission_data[field_name] = payload.get("value")
        applied[field_name] = payload
    return applied


def run_single_field_verification(field: FormField, rule, value):
    provider = (rule.get("provider") or rule.get("type") or "").strip().lower()
    external_key = (
        (rule.get("external_key") or rule.get("key") or field.name or "")
        .strip()
        .lower()
    )
    params = rule.get("params") or {}

    if provider == "regex":
        import re

        pattern = rule.get("pattern") or params.get("pattern")
        if not pattern:
            return {
                "ok": False,
                "provider": "regex",
                "external_key": external_key,
                "type": "regex",
                "reason": "missing_pattern",
                "value": value,
            }
        return {
            "ok": bool(re.match(pattern, str(value))),
            "provider": "regex",
            "external_key": external_key,
            "type": "regex",
            "value": value,
        }

    if provider in ("inventory", "external_lookup"):
        inv = InventoryService()
        key = external_key or field.name.lower()
        if "sales" in key or "pricebook" in key or "sku" in key:
            ok = inv.validate_sales_list_number(str(value).strip())
        else:
            ok = inv.validate_part_number(str(value).strip())
        return {
            "ok": ok,
            "provider": "inventory",
            "external_key": external_key,
            "type": "external_lookup",
            "triggers_auto_reject": bool(rule.get("triggers_auto_reject")),
            "value": value,
        }

    verifier = VerificationService()
    result = verifier.verify_lookup(provider, external_key, value, params)
    result.setdefault("provider", provider)
    result.setdefault("external_key", external_key)
    result.setdefault("type", "external_lookup")
    if provider in (
        "verification",
        "tracker",
        "realtime_tracker",
        "third_party_tracker",
    ) or str(provider).startswith("tracker:"):
        result.setdefault("type", "tracker_lookup")
    result.setdefault("triggers_auto_reject", bool(rule.get("triggers_auto_reject")))
    result.setdefault("value", value)
    return result


def run_field_verification(field: FormField, rule, submission_data: Dict):
    value = submission_data.get(field.name)
    if value is None or str(value).strip() == "":
        return {"ok": None, "reason": "empty", "type": "external_lookup"}

    if not isinstance(rule, dict):
        return {"ok": None, "reason": "invalid_rule", "type": "external_lookup"}

    params = rule.get("params") or {}
    if not bool(params.get("verify_each_separated_value")):
        return run_single_field_verification(field, rule, value)

    separator = normalize_bulk_separator(
        params.get("value_separator") or params.get("separator")
    )
    raw_value = str(value)
    if separator == "\n":
        pieces = [piece.strip() for piece in raw_value.splitlines() if piece.strip()]
    else:
        pieces = [
            piece.strip() for piece in raw_value.split(separator) if piece.strip()
        ]

    if not pieces:
        return {"ok": None, "reason": "empty", "type": "external_lookup"}

    item_results = []
    for piece in pieces:
        single = run_single_field_verification(field, rule, piece)
        item_results.append({"value": piece, **single})

    first = item_results[0] if item_results else {}
    return {
        "ok": all(item.get("ok") is True for item in item_results),
        "bulk": True,
        "count": len(item_results),
        "separator": separator,
        "items": item_results,
        "provider": first.get("provider"),
        "external_key": first.get("external_key"),
        "type": first.get("type", "external_lookup"),
        "triggers_auto_reject": bool(rule.get("triggers_auto_reject")),
    }
