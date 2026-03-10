import importlib.util
from pathlib import Path
import re

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
        assert refreshed.active_quote_set == "motivational"
        # each built-in set should still be populated and at target length
        for name in SiteConfig.DEFAULT_QUOTE_SETS:
            assert refreshed.rolling_quote_sets[name]
            assert len(refreshed.rolling_quote_sets[name]) == 30, "set {name} length"
        # the engineering set should contain the original quote and have been padded
        eng = refreshed.rolling_quote_sets["engineering"]
        assert eng[0] == "Ship it."
        assert len(eng) == 30


def test_builtin_quote_sets_use_themed_padding_instead_of_placeholders():
    for name, quotes in SiteConfig.DEFAULT_QUOTE_SETS.items():
        assert len(quotes) == 30
        assert not any(
            re.fullmatch(rf"{re.escape(str(name))} quote \d+", str(quote), re.IGNORECASE)
            for quote in quotes
        )

    assert "chores" in SiteConfig.DEFAULT_QUOTE_SETS
    assert any("dish" in quote.lower() or "counter" in quote.lower() for quote in SiteConfig.DEFAULT_QUOTE_SETS["chores"])


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
        custom = refreshed.rolling_quote_sets["custom"]
        assert custom[0] == "Own the day."
        assert len(custom) == 30
        # default should also be padded to 30 while preserving the original
        default = refreshed.rolling_quote_sets["default"]
        assert default[0] == "Custom default."
        assert len(default) == 30

def test_release_task_adds_company_url_column(app):
    # simulate legacy schema missing the company_url column and run main()
    module = _load_release_tasks_module()
    from sqlalchemy import inspect, text
    from app import db

    with app.app_context():
        engine = db.engine
        insp = inspect(engine)
        cols = {c['name'] for c in insp.get_columns('site_config')}
        if 'company_url' in cols:
            with engine.begin() as conn:
                # sqlite doesn't support drop column easily; instead recreate table
                conn.execute(text('ALTER TABLE site_config RENAME TO site_config_old'))
                # recreate minimal schema without company_url
                conn.execute(text('CREATE TABLE site_config (id INTEGER PRIMARY KEY)'))
                conn.execute(text('INSERT INTO site_config(id) SELECT id FROM site_config_old'))
                conn.execute(text('DROP TABLE site_config_old'))
        # ensure it's gone
        insp2 = inspect(engine)
        assert 'company_url' not in {c['name'] for c in insp2.get_columns('site_config')}

        # run main which should trigger schema safety net
        module.main()

        insp3 = inspect(engine)
        assert 'company_url' in {c['name'] for c in insp3.get_columns('site_config')}