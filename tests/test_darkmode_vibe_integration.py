def test_dark_mode_vibe_logic_present_in_theme_script():
    path = "app/static/app.js"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "function isDarkModeEnabled()" in content
    assert "document.body.classList.contains('dark-mode')" in content
    assert 'root.style.setProperty("--surface", mixHex(p.accent, "#1e1e1e", 0.10));' in content
    assert 'root.style.setProperty("--nav-bg", mixHex(p.accent, "#202124", 0.18));' in content
    assert '#121212' in content
