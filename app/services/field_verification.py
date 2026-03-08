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


def run_single_field_verification(field: FormField, rule, value):
    provider = (rule.get("provider") or rule.get("type") or "").strip().lower()
    external_key = (
        rule.get("external_key") or rule.get("key") or field.name or ""
    ).strip().lower()
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
            }
        return {
            "ok": bool(re.match(pattern, str(value))),
            "provider": "regex",
            "external_key": external_key,
            "type": "regex",
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
        }

    verifier = VerificationService()
    result = verifier.verify_lookup(provider, external_key, value, params)
    result.setdefault("provider", provider)
    result.setdefault("external_key", external_key)
    result.setdefault("type", "external_lookup")
    result.setdefault("triggers_auto_reject", bool(rule.get("triggers_auto_reject")))
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
        pieces = [piece.strip() for piece in raw_value.split(separator) if piece.strip()]

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