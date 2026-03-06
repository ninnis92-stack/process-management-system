"""Inventory integration skeleton.

This service provides a minimal interface that can be implemented to
connect to an external inventory database or API. By default (no
connector configured) methods return None to indicate "unknown" so the
application continues to behave as a prototype.
"""
from typing import Optional
from flask import current_app


class InventoryService:
    def __init__(self):
        # Example config keys: INVENTORY_ENABLED, INVENTORY_DSN
        self.enabled = bool(current_app.config.get("INVENTORY_ENABLED", False))
        self.dsn = current_app.config.get("INVENTORY_DSN")
        # Placeholder for a DB/HTTP client that can be wired later
        self._client = None
        if self.enabled and self.dsn:
            # TODO: instantiate client using DSN (psycopg / requests, etc.)
            try:
                # Lazy connect placeholder
                self._client = None
            except Exception:
                self._client = None

    def validate_part_number(self, part_no: str) -> Optional[bool]:
        """Validate a part number against inventory.

        Returns:
          - True if part exists/valid
          - False if part definitively does not exist
          - None if inventory connector is not configured or unknown
        """
        # Backwards-compatible wrapper around `get_stock_count` which is
        # more informative for integrations.
        cnt = self.get_stock_count(part_no)
        if cnt is None:
            return None
        return bool(cnt)

    def get_stock_count(self, part_no: str) -> Optional[int]:
        """Return an integer stock count for the given part number.

        Returns:
          - non-negative integer when the connector can determine stock levels
          - 0 when out of stock
          - None when the connector is not configured or the quantity is unknown

        Default implementation returns None (unknown) so the app fails-open
        until a real connector is wired.
        """
        if not self.enabled or not self._client:
            return None

        try:
            # Replace with real lookup logic when integrating. Example:
            # resp = self._client.get(f"/parts/{quote(part_no)}")
            # if resp.status_code == 404: return 0
            # data = resp.json(); return int(data.get('available', 0))
            return None
        except Exception:
            return None

    def validate_sales_list_number(self, number: str) -> Optional[bool]:
        """Validate a sales list / price book number.

        Same return semantics as `validate_part_number`.
        """
        if not self.enabled or not self._client:
            return None
        try:
            return None
        except Exception:
            return None

