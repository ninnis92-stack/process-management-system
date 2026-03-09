def test_dark_mode_vibe_logic_present_in_theme_script():
    path = "app/static/app.js"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "function isDarkModeEnabled()" in content
    assert "document.body.classList.contains('dark-mode')" in content

    # dark-mode branch should tint a bunch of palettes with the accent
    assert 'root.style.setProperty("--nav-bg", mixHex(p.accent, "#0b1220", 0.16));' in content
    assert 'root.style.setProperty("--nav-text", mixHex("#e8f0fb", p.accent, 0.08));' in content
    assert 'root.style.setProperty("--body-text", mixHex("#e5eef8", p.accent, 0.06));' in content
    assert 'root.style.setProperty("--surface", mixHex(p.accent, "#111c2d", 0.08));' in content
    assert 'root.style.setProperty("--surface-2", mixHex(p.accent, "#18263b", 0.06));' in content
    assert 'root.style.setProperty("--surface-3", mixHex(p.accent, "#21344e", 0.08));' in content
    assert '#08111f' in content  # page-bg dark base

    # light-mode branch must still set sane defaults and reset text colors
    assert 'root.style.setProperty("--nav-text", mixHex("#f8fbff"' in content
    assert 'root.style.setProperty("--body-text", mixHex("#132033"' in content

    # banner and other supplemental variables exist in both branches
    assert 'root.style.setProperty("--banner-bg"' in content
    assert 'root.style.setProperty("--banner-border"' in content
    assert 'root.style.setProperty("--banner-shadow"' in content
