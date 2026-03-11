import json
import sys

from app import create_app
from app.models import SiteConfig

app = create_app()

with app.app_context():
    cfg = SiteConfig.get()
    quote_sets = SiteConfig.normalize_quote_sets(
        getattr(cfg, "rolling_quote_sets", None)
    )
    active = str(getattr(cfg, "active_quote_set", "") or "").strip().lower()
    if active not in quote_sets or active == "default":
        active = "motivational" if "motivational" in quote_sets else "default"

    changed = False
    if quote_sets != (getattr(cfg, "rolling_quote_sets", None) or {}):
        cfg._rolling_quote_sets = json.dumps(quote_sets)
        changed = True
    if active != getattr(cfg, "active_quote_set", None):
        cfg.active_quote_set = active
        changed = True
    if changed:
        from app.extensions import db

        db.session.commit()

    print("Active quote set:", cfg.active_quote_set)
    print("Available sets:")
    for k, v in quote_sets.items():
        print(f"- {k} ({len(v)} lines)")

    missing = [k for k, v in quote_sets.items() if not v]
    if missing:
        print("Missing content:", ", ".join(missing), file=sys.stderr)
        raise SystemExit(1)

    print("\nSample lines:")
    for i, line in enumerate((quote_sets.get(active) or [])[:5]):
        print(f"{i+1}. {line}")
