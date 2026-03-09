def test_dark_mode_vibe_logic_present_in_theme_script():
    path = "app/static/app.js"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "function isDarkModeEnabled()" in content
    assert "document.body.classList.contains('dark-mode')" in content

    # dark mode now uses a curated compatible subset rather than disabling
    # vibe support entirely.
    assert "const darkModeCompatiblePaletteIndexes = [0, 4, 5, 7, 14, 18, 23, 24];" in content
    assert "function isDarkModeCompatiblePalette(idx)" in content
    assert "function getEffectivePaletteIndex(idx)" in content
    assert "function syncVibeControlAvailability()" in content
    assert 'if (darkMode) {' in content
    assert 'root.style.setProperty("--nav-bg", mixHex(p.accent, "#0b1220", 0.30));' in content
    assert 'root.style.setProperty("--surface", mixHex(p.accent, "#111c2d", 0.20));' in content
    assert 'const next = darkModeCompatiblePaletteIndexes[' in content

    # light-mode branch must still set sane defaults and reset text colors
    assert 'root.style.setProperty("--nav-text", mixHex("#f8fbff"' in content
    assert 'root.style.setProperty("--body-text", mixHex("#132033"' in content

    # banner and other supplemental variables still exist for light mode
    assert 'root.style.setProperty("--banner-bg"' in content
    assert 'root.style.setProperty("--banner-border"' in content
    assert 'root.style.setProperty("--banner-shadow"' in content
