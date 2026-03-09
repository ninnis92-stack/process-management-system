def test_dark_mode_theme_tokens_are_not_overridden_by_light_theme_classes():
    path = "app/static/styles.css"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "body.no-vibe:not(.dark-mode)" in content
    assert "body.theme-preset-ocean:not(.dark-mode)" in content
    assert "body.theme-preset-forest:not(.dark-mode)" in content
    assert "body.theme-preset-sunset:not(.dark-mode)" in content
    assert "body.theme-preset-midnight:not(.dark-mode)" in content
    assert "body.theme-preset-ocean.dark-mode" in content
    assert "body.theme-preset-forest.dark-mode" in content
    assert "body.theme-preset-sunset.dark-mode" in content
    assert "body.theme-preset-midnight.dark-mode" in content
    # ensure dark mode uses accent variables for vibe support
    assert "--accent" in content
    # light mode should declare a nav-text default so the navbar is
    # readable once vibe scripts run (nav bars are dark, so default text is light)
    assert "--nav-text: #f8fbff" in content
    assert "dark-mode .btn-primary" in content and "var(--accent)" in content


def test_dark_mode_brand_adoption_keeps_brand_accent_tokens():
    path = "app/static/styles.css"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "body.theme-preset-forest.dark-mode" in content
    assert "--accent: #7bc96f;" in content
    assert "--accent-rgb: 123, 201, 111;" in content
    assert "--banner-border: rgba(123, 201, 111, 0.24);" in content