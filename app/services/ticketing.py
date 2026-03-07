from typing import Dict, Optional
from flask import current_app


class TicketingClient:
    """Stub adapter for integrating with external work-management systems (Jira, Zendesk, etc.).

    - If `TICKETING_ENABLED` is False or no endpoint configured, this will return a prototype response (non-blocking).
    - Providers should implement `create_ticket(summary, description, metadata)` returning an identifier and URL.
    """

    def __init__(self):
        cfg = current_app.config
        self.enabled = cfg.get("TICKETING_ENABLED", False)
        self.url = cfg.get("TICKETING_URL")
        self.token = cfg.get("TICKETING_TOKEN")
        self.timeout = int(cfg.get("TICKETING_TIMEOUT", 5))

    def create_ticket(
        self, summary: str, description: str, metadata: Optional[Dict] = None
    ) -> Dict:
        if not self.enabled or not self.url:
            # Prototype behavior: return a fake ticket id and note
            return {
                "ok": None,
                "ticket_id": f"PROTOTYPE-{int(__import__('time').time())}",
                "url": None,
            }

        # Real implementation should POST to provider API using requests and return structured result.
        try:
            # Placeholder for future real request
            return {"ok": True, "ticket_id": "TICKET-12345", "url": self.url}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
