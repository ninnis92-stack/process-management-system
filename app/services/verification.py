from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import requests
from flask import current_app
from flask_login import current_user

from ..models import IntegrationConfig
from .integrations import normalize_integration_config


def _deep_merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base or {})
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _truthy(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in {
        "1",
        "true",
        "yes",
        "y",
        "ok",
        "valid",
        "exists",
        "found",
        "available",
        "pass",
        "passed",
    }:
        return True
    if text in {
        "0",
        "false",
        "no",
        "n",
        "invalid",
        "missing",
        "not_found",
        "error",
        "fail",
        "failed",
        "unavailable",
    }:
        return False
    return None


def _get_nested(data: Any, path: str | None, default: Any = None) -> Any:
    if not path:
        return default
    current = data
    for segment in [p for p in str(path).split(".") if p]:
        if isinstance(current, dict):
            if segment not in current:
                return default
            current = current[segment]
            continue
        if isinstance(current, list) and segment.isdigit():
            index = int(segment)
            if index >= len(current):
                return default
            current = current[index]
            continue
        return default
    return current


class _SafeFormatDict(dict):
    def __missing__(self, key):
        return "{" + str(key) + "}"


class VerificationService:
    """Small adapter to call external verification APIs for parts and methods.

    Behavior:
      - If the relevant API is disabled or URL not configured, returns {'ok': None, 'reason': 'disabled'}
      - On success, returns {'ok': True/False, 'details': <api response dict>}.
      - On error, returns {'ok': False, 'reason': 'error', 'error': <message>}.
    """

    def __init__(self):
        cfg = current_app.config
        self.part_enabled = cfg.get("PART_API_ENABLED", False)
        self.part_url = cfg.get("PART_API_URL")
        self.part_token = cfg.get("PART_API_TOKEN")
        self.part_timeout = cfg.get("PART_API_TIMEOUT", 5)

        self.method_enabled = cfg.get("METHOD_API_ENABLED", False)
        self.method_url = cfg.get("METHOD_API_URL")
        self.method_token = cfg.get("METHOD_API_TOKEN")
        self.method_timeout = cfg.get("METHOD_API_TIMEOUT", 5)

        self.session = requests.Session()
        # Don't blindly set Authorization header if no token available; prefer per-request headers

    def _call_api(
        self, url: str, params: dict, token: Optional[str], timeout: int
    ) -> Dict:
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            resp = self.session.get(
                url, params=params, headers=headers, timeout=timeout
            )
            resp.raise_for_status()
            try:
                return {"ok": True, "details": resp.json()}
            except ValueError:
                return {"ok": True, "details": {"raw": resp.text}}
        except Exception as exc:
            return {"ok": False, "reason": "error", "error": str(exc)}

    def _render_template_value(self, raw_value: Any, context: Dict[str, Any]) -> Any:
        if isinstance(raw_value, dict):
            return {
                str(key): self._render_template_value(value, context)
                for key, value in raw_value.items()
            }
        if isinstance(raw_value, list):
            return [self._render_template_value(item, context) for item in raw_value]
        if isinstance(raw_value, str):
            try:
                return raw_value.format_map(_SafeFormatDict(context))
            except Exception:
                return raw_value
        return raw_value

    def _resolve_department(self, options: Optional[Dict[str, Any]]) -> Optional[str]:
        options = options or {}
        dept = (
            options.get("department")
            or options.get("integration_department")
            or options.get("owner_department")
        )
        if dept:
            return str(dept).strip().upper() or None
        try:
            if getattr(current_user, "is_authenticated", False):
                dept = getattr(current_user, "department", None)
                return str(dept).strip().upper() if dept else None
        except Exception:
            pass
        return None

    def _load_verification_config(
        self, options: Optional[Dict[str, Any]]
    ) -> tuple[Optional[IntegrationConfig], Optional[Dict[str, Any]]]:
        dept = self._resolve_department(options)
        query = IntegrationConfig.query.filter_by(kind="verification", enabled=True)
        if dept:
            cfg = query.filter_by(department=dept).first()
            if cfg:
                return cfg, normalize_integration_config("verification", cfg.config)
        cfg = query.order_by(IntegrationConfig.department.asc()).first()
        if not cfg:
            return None, None
        return cfg, normalize_integration_config("verification", cfg.config)

    def _rule_matches(
        self,
        rule: Dict[str, Any],
        *,
        external_key: str,
        value: Any,
        options: Optional[Dict[str, Any]],
    ) -> bool:
        if not isinstance(rule, dict):
            return False
        options = options or {}
        raw_value = "" if value is None else str(value)
        normalized_value = raw_value.strip()
        lowered_value = normalized_value.lower()
        normalized_key = (external_key or "").strip().lower()

        allowed_keys = [
            item.lower()
            for item in _coerce_list(rule.get("external_keys") or rule.get("fields"))
        ]
        if allowed_keys and normalized_key not in allowed_keys:
            return False

        option_matches = rule.get("option_matches") or {}
        if isinstance(option_matches, dict):
            for key, expected in option_matches.items():
                actual = options.get(key)
                if isinstance(expected, list):
                    normalized_expected = {
                        str(item).strip().lower() for item in expected
                    }
                    if str(actual).strip().lower() not in normalized_expected:
                        return False
                elif str(actual).strip().lower() != str(expected).strip().lower():
                    return False

        equals_any = _coerce_list(rule.get("equals") or rule.get("equals_any"))
        if equals_any and normalized_value not in equals_any:
            return False

        contains_any = [
            item.lower()
            for item in _coerce_list(rule.get("contains") or rule.get("contains_any"))
        ]
        if contains_any and not any(piece in lowered_value for piece in contains_any):
            return False

        starts_any = [
            item.lower()
            for item in _coerce_list(
                rule.get("starts_with") or rule.get("starts_with_any")
            )
        ]
        if starts_any and not any(
            lowered_value.startswith(piece) for piece in starts_any
        ):
            return False

        ends_any = [
            item.lower()
            for item in _coerce_list(rule.get("ends_with") or rule.get("ends_with_any"))
        ]
        if ends_any and not any(lowered_value.endswith(piece) for piece in ends_any):
            return False

        pattern = rule.get("regex") or rule.get("match_regex") or rule.get("pattern")
        if pattern:
            try:
                if not re.search(str(pattern), normalized_value):
                    return False
            except re.error:
                return False

        min_length = rule.get("min_length")
        if min_length is not None:
            try:
                if len(normalized_value) < int(min_length):
                    return False
            except Exception:
                return False

        max_length = rule.get("max_length")
        if max_length is not None:
            try:
                if len(normalized_value) > int(max_length):
                    return False
            except Exception:
                return False

        return True

    def _select_tracker(
        self,
        config: Dict[str, Any],
        *,
        external_key: str,
        value: Any,
        options: Optional[Dict[str, Any]],
    ) -> tuple[str, Dict[str, Any], Optional[Dict[str, Any]]]:
        routing = config.get("routing") or {}
        trackers = config.get("trackers") or {}
        tracker_handle = (
            (options or {}).get("tracker_handle")
            or (options or {}).get("provider_handle")
            or routing.get("default_tracker")
            or "default"
        )
        matched_rule = None
        for rule in routing.get("rules") or []:
            if self._rule_matches(
                rule, external_key=external_key, value=value, options=options
            ):
                tracker_handle = (
                    str(rule.get("tracker") or tracker_handle or "default").strip()
                    or "default"
                )
                matched_rule = rule
                break

        if isinstance(trackers, dict) and trackers:
            selected = trackers.get(tracker_handle)
            if selected is None and "default" in trackers:
                tracker_handle = "default"
                selected = trackers.get("default")
            if selected is None:
                tracker_handle, selected = next(iter(trackers.items()))
            return (
                tracker_handle,
                _deep_merge(config, selected if isinstance(selected, dict) else {}),
                matched_rule,
            )

        return tracker_handle, config, matched_rule

    def _apply_auth(
        self, auth_cfg: Dict[str, Any], headers: Dict[str, str], params: Dict[str, Any]
    ) -> None:
        auth_cfg = auth_cfg or {}
        auth_type = (auth_cfg.get("type") or "none").strip().lower()
        token = None
        token_env = (auth_cfg.get("token_env") or "").strip()
        if token_env:
            token = os.getenv(token_env)
        token = token or auth_cfg.get("token") or auth_cfg.get("token_value")

        if auth_type in {"token", "bearer"} and token:
            header_name = auth_cfg.get("header_name") or "Authorization"
            scheme = auth_cfg.get("scheme") or "Bearer"
            headers[str(header_name)] = f"{scheme} {token}".strip()
        elif auth_type == "header":
            header_name = auth_cfg.get("header_name") or "X-Api-Key"
            header_value = auth_cfg.get("header_value") or token or ""
            if header_value:
                headers[str(header_name)] = str(header_value)
        elif auth_type == "query" and token:
            param_name = auth_cfg.get("param_name") or "api_key"
            params[str(param_name)] = token

    def _normalize_endpoint_url(
        self, endpoints: Dict[str, Any], tracker_cfg: Dict[str, Any]
    ) -> Optional[str]:
        endpoint = (
            endpoints.get("validate")
            or endpoints.get("lookup")
            or endpoints.get("url")
            or tracker_cfg.get("url")
        )
        if not endpoint:
            return None
        endpoint = str(endpoint).strip()
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            return endpoint
        base_url = (
            endpoints.get("base_url")
            or tracker_cfg.get("base_url")
            or tracker_cfg.get("endpoint_base")
            or ""
        )
        if not base_url:
            return endpoint
        return urljoin(str(base_url).rstrip("/") + "/", endpoint.lstrip("/"))

    def _extract_result(
        self, payload: Any, response_cfg: Dict[str, Any], *, status_ok: bool
    ) -> tuple[bool, Any, Optional[str]]:
        response_cfg = response_cfg or {}
        details = _get_nested(payload, response_cfg.get("detail_path"), payload)
        reason = _get_nested(payload, response_cfg.get("reason_path"), None)

        ok_value = _get_nested(payload, response_cfg.get("ok_path"), None)
        if ok_value is None and isinstance(payload, dict):
            for candidate in ("ok", "valid", "exists", "found", "available"):
                if candidate in payload:
                    ok_value = payload.get(candidate)
                    break
            if ok_value is None and isinstance(payload.get("details"), dict):
                detail_dict = payload.get("details") or {}
                for candidate in (
                    "valid",
                    "exists",
                    "found",
                    "available",
                    "in_stock",
                    "populated",
                ):
                    if candidate in detail_dict:
                        ok_value = detail_dict.get(candidate)
                        break
                if ok_value is None:
                    for candidate in (
                        "stock_count",
                        "available_count",
                        "quantity",
                        "qty",
                        "on_hand",
                    ):
                        if candidate in detail_dict:
                            ok_value = int(detail_dict.get(candidate) or 0) > 0
                            break

        resolved_ok = _truthy(ok_value)
        if resolved_ok is None:
            resolved_ok = bool(status_ok)
        if not resolved_ok and not reason:
            reason = _get_nested(payload, "message", None) or _get_nested(
                payload, "error", None
            )
        return bool(resolved_ok), details, None if reason is None else str(reason)

    def _verify_with_tracker_config(
        self,
        config: Dict[str, Any],
        *,
        external_key: str,
        value: Any,
        options: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        tracker_handle, tracker_cfg, matched_rule = self._select_tracker(
            config,
            external_key=external_key,
            value=value,
            options=options,
        )
        endpoints = tracker_cfg.get("endpoints") or {}
        request_cfg = tracker_cfg.get("request") or {}
        response_cfg = tracker_cfg.get("response") or {}
        url = self._normalize_endpoint_url(endpoints, tracker_cfg)
        if not url:
            return {
                "ok": None,
                "reason": "disabled",
                "tracker_handle": tracker_handle,
                "matched_rule": (
                    (matched_rule or {}).get("name")
                    if isinstance(matched_rule, dict)
                    else None
                ),
            }

        context = {
            "value": str(value).strip(),
            "external_key": (external_key or "").strip(),
            "department": self._resolve_department(options) or "",
            **dict(options or {}),
        }
        default_query = {"value": "{value}", "field": "{external_key}"}
        params = self._render_template_value(
            request_cfg.get("query_template")
            or request_cfg.get("query")
            or default_query,
            context,
        )
        headers = self._render_template_value(request_cfg.get("headers") or {}, context)
        body = self._render_template_value(
            request_cfg.get("body_template") or request_cfg.get("body") or {}, context
        )
        payload_location = (
            (
                request_cfg.get("payload_location")
                or (
                    "query"
                    if (request_cfg.get("method") or "GET").upper() == "GET"
                    else "json"
                )
            )
            .strip()
            .lower()
        )
        method = (request_cfg.get("method") or "GET").strip().upper()
        timeout = int(
            request_cfg.get("timeout_seconds")
            or request_cfg.get("timeout")
            or tracker_cfg.get("timeout")
            or 5
        )
        self._apply_auth(tracker_cfg.get("auth") or {}, headers, params)

        request_kwargs: Dict[str, Any] = {
            "headers": headers,
            "params": params,
            "timeout": timeout,
        }
        if payload_location == "json":
            request_kwargs["json"] = body
        elif payload_location == "form":
            request_kwargs["data"] = body

        try:
            resp = self.session.request(method, url, **request_kwargs)
            try:
                payload = resp.json()
            except ValueError:
                payload = {"raw": resp.text}
            ok, details, reason = self._extract_result(
                payload, response_cfg, status_ok=resp.ok
            )
            return {
                "ok": ok,
                "details": details,
                "reason": reason,
                "tracker_handle": tracker_handle,
                "tracker_url": url,
                "matched_rule": (
                    (matched_rule or {}).get("name")
                    if isinstance(matched_rule, dict)
                    else None
                ),
                "status_code": resp.status_code,
            }
        except Exception as exc:
            return {
                "ok": False,
                "reason": "error",
                "error": str(exc),
                "tracker_handle": tracker_handle,
                "tracker_url": url,
                "matched_rule": (
                    (matched_rule or {}).get("name")
                    if isinstance(matched_rule, dict)
                    else None
                ),
            }

    def _verify_with_integration_configs(
        self,
        external_key: Optional[str],
        value: Any,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        cfg_row, cfg = self._load_verification_config(options)
        if not cfg:
            return {"ok": None, "reason": "disabled"}
        result = self._verify_with_tracker_config(
            cfg,
            external_key=(external_key or "value").strip().lower(),
            value=value,
            options=options,
        )
        if cfg_row:
            result.setdefault("integration_department", cfg_row.department)
            result.setdefault("integration_id", cfg_row.id)
        return result

    def verify_part_number(self, part_number: str) -> Dict:
        if not part_number:
            return {"ok": False, "reason": "empty"}
        if not self.part_enabled or not self.part_url:
            return {"ok": None, "reason": "disabled"}
        # Recommend provider implement GET /validate?part=... returning JSON {valid: true/false,...}
        url = self.part_url.rstrip("/") + "/validate"
        return self._call_api(
            url, {"part": part_number}, self.part_token, self.part_timeout
        )

    def verify_method(self, method_id: str) -> Dict:
        if not method_id:
            return {"ok": False, "reason": "empty"}
        if not self.method_enabled or not self.method_url:
            return {"ok": None, "reason": "disabled"}
        # Recommend provider implement GET /validate?method=... returning JSON {valid: true/false,...}
        url = self.method_url.rstrip("/") + "/validate"
        return self._call_api(
            url, {"method": method_id}, self.method_token, self.method_timeout
        )

    def verify_lookup(
        self,
        provider: str,
        external_key: Optional[str],
        value: Any,
        options: Optional[Dict] = None,
    ) -> Dict:
        """Generic provider-aware lookup used by dynamic field verification.

        Returns a dict with `ok` and optional `details` / `reason`.
        The method is intentionally fail-open when a provider is disabled or
        unavailable so submission flows can decide how strictly to act.
        """
        options = options or {}
        provider_n = (provider or "").strip().lower()
        key_n = (external_key or "").strip().lower()
        if value is None or str(value).strip() == "":
            return {"ok": None, "reason": "empty"}

        if provider_n in ("part", "parts", "part_number"):
            return self.verify_part_number(str(value).strip())
        if provider_n in ("method", "instructions"):
            return self.verify_method(str(value).strip())
        if provider_n.startswith("tracker:"):
            options = dict(options or {})
            options.setdefault("tracker_handle", provider_n.split(":", 1)[1])
            return self._verify_with_integration_configs(key_n, value, options)
        if provider_n in (
            "verification",
            "tracker",
            "realtime_tracker",
            "third_party_tracker",
        ):
            return self._verify_with_integration_configs(key_n, value, options)
        if provider_n == "api":
            routed = self._verify_with_integration_configs(key_n, value, options)
            if routed.get("reason") != "disabled":
                return routed
            kind = (options.get("kind") or key_n or "").strip().lower()
            if "method" in kind or "instruction" in kind:
                return self.verify_method(str(value).strip())
            return self.verify_part_number(str(value).strip())

        return {"ok": None, "reason": "unsupported_provider", "provider": provider}
