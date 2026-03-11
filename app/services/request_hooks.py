from __future__ import annotations

from typing import Optional

from sqlalchemy import event, inspect

from ..extensions import db


def init_request_hooks(app=None):
    # Late-import to avoid circular imports at module import time
    try:
        from ..models import Request as ReqModel
        from .rule_engine import evaluate_rules_for_event
    except Exception:
        return

    def _after_insert(mapper, connection, target):
        try:
            evaluate_rules_for_event("request_created", target)
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass

    def _after_update(mapper, connection, target):
        try:
            insp = inspect(target)
            # If the status attribute changed, fire the status-changed event
            status_hist = insp.attrs.status.history
            if status_hist.has_changes():
                evaluate_rules_for_event("request_status_changed", target)
            # Also evaluate general update triggers
            evaluate_rules_for_event("request_updated", target)
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass

    # Register listeners (idempotent across repeated init attempts)
    try:
        event.listen(ReqModel, "after_insert", _after_insert)
        event.listen(ReqModel, "after_update", _after_update)
    except Exception:
        # If the model/table isn't available yet (tests/migrations), skip silently
        pass
