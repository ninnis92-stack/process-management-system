from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app


class SlackService:
    """Minimal Slack webhook poster for prototype use.

    Expects a full webhook URL to be supplied by the rule/action payload.
    In production, prefer a secured provider integration rather than raw webhooks.
    """

    def post_message(self, webhook_url: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not webhook_url:
            raise ValueError("missing webhook url")
        body = json.dumps(payload).encode("utf-8")
        req = Request(webhook_url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urlopen(req, timeout=10) as resp:
                resp.read()
            current_app.logger.info("SlackService: posted message to webhook")
            return {"ok": True}
        except (HTTPError, URLError) as exc:
            current_app.logger.exception(
                "SlackService: failed to post message: %s", exc
            )
            return {"ok": False, "error": str(exc)}
