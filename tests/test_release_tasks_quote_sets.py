import importlib.util
from pathlib import Path

from app.extensions import db
from app.models import SiteConfig


def _load_release_tasks_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "release_tasks.py"
    spec = importlib.util.spec_from_file_location("release_tasks_for_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_release_task_normalizes_quote_sets_and_repairs_active_set(app):
    module = _load_release_tasks_module()

    with app.app_context():
        cfg = SiteConfig.get()
        cfg._rolling_quote_sets = '{"default": [], "engineering": ["Ship it."], "motivational": []}'
        cfg.active_quote_set = "unknown"
        db.session.commit()

        module._ensure_quote_sets_ready()

        refreshed = SiteConfig.get()
        assert refreshed.active_quote_set == "default"
        for name in SiteConfig.DEFAULT_QUOTE_SETS:
            assert refreshed.rolling_quote_sets[name]
        assert refreshed.rolling_quote_sets["engineering"] == ["Ship it."]


def test_release_task_keeps_custom_quote_sets_with_content(app):
    module = _load_release_tasks_module()

    with app.app_context():
        cfg = SiteConfig.get()
        cfg._rolling_quote_sets = '{"custom": ["Own the day."], "default": ["Custom default."]}'
        cfg.active_quote_set = "custom"
        db.session.commit()

        module._ensure_quote_sets_ready()

        refreshed = SiteConfig.get()
        assert refreshed.active_quote_set == "custom"
        assert refreshed.rolling_quote_sets["custom"] == ["Own the day."]
        assert refreshed.rolling_quote_sets["default"] == ["Custom default."]
