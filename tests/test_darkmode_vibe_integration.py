def test_dark_mode_vibe_logic_present_in_theme_script():
    path = "app/static/app.js"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "function isDarkModeEnabled()" in content
    assert "document.body.classList.contains('dark-mode')" in content
    assert 'root.style.setProperty("--surface", mixHex(p.accent, "#111c2d", 0.08));' in content
    assert 'root.style.setProperty("--surface-2", mixHex(p.accent, "#18263b", 0.06));' in content
    assert 'root.style.setProperty("--nav-bg", mixHex(p.accent, "#0b1220", 0.16));' in content
    assert '#08111f' in content
    # new variables added for improved vibe support
    assert 'root.style.setProperty("--nav-text"' in content
    assert 'root.style.setProperty("--body-text"' in content
    # the light-mode branch of applyTheme should also reset nav/body text
    assert 'root.style.setProperty("--nav-text", mixHex("#f8fbff"' in content
    assert 'root.style.setProperty("--banner-bg"' in content
    assert 'root.style.setProperty("--surface-3"' in content
