def test_dark_mode_theme_tokens_are_not_overridden_by_light_theme_classes():
    path = "app/static/styles.css"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "body.no-vibe:not(.dark-mode)" in content
    assert "body.theme-preset-ocean:not(.dark-mode)" in content
    assert "body.theme-preset-forest:not(.dark-mode)" in content
    assert "body.theme-preset-sunset:not(.dark-mode)" in content
    assert "body.theme-preset-midnight:not(.dark-mode)" in content