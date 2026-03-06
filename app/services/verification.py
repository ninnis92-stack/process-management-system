from typing import Optional, Dict, Any
from flask import current_app
import requests


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

    def _call_api(self, url: str, params: dict, token: Optional[str], timeout: int) -> Dict:
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            resp = self.session.get(url, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            try:
                return {"ok": True, "details": resp.json()}
            except ValueError:
                return {"ok": True, "details": {"raw": resp.text}}
        except Exception as exc:
            return {"ok": False, "reason": "error", "error": str(exc)}

    def verify_part_number(self, part_number: str) -> Dict:
        if not part_number:
            return {"ok": False, "reason": "empty"}
        if not self.part_enabled or not self.part_url:
            return {"ok": None, "reason": "disabled"}
        # Recommend provider implement GET /validate?part=... returning JSON {valid: true/false,...}
        url = self.part_url.rstrip("/") + "/validate"
        return self._call_api(url, {"part": part_number}, self.part_token, self.part_timeout)

    def verify_method(self, method_id: str) -> Dict:
        if not method_id:
            return {"ok": False, "reason": "empty"}
        if not self.method_enabled or not self.method_url:
            return {"ok": None, "reason": "disabled"}
        # Recommend provider implement GET /validate?method=... returning JSON {valid: true/false,...}
        url = self.method_url.rstrip("/") + "/validate"
        return self._call_api(url, {"method": method_id}, self.method_token, self.method_timeout)

    def verify_lookup(self, provider: str, external_key: Optional[str], value: Any, options: Optional[Dict] = None) -> Dict:
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
        if provider_n in ("verification", "api"):
            kind = (options.get("kind") or key_n or "").strip().lower()
            if "method" in kind or "instruction" in kind:
                return self.verify_method(str(value).strip())
            return self.verify_part_number(str(value).strip())

        return {"ok": None, "reason": "unsupported_provider", "provider": provider}
