def test_dark_mode_vibe_logic_present_in_theme_script():
    path = "frontend/js/modules/theme.js"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "function isDarkModeEnabled()" in content
    assert "function getUserVibeIndex()" in content
    assert "document.body.classList.contains('dark-mode')" in content

    # dark mode now disables vibe support entirely; the script should bail
    # out early and not apply any theme overrides when dark mode is active.
    assert "// when dark mode is active we ignore vibes" in content
    assert "function syncVibeControlAvailability()" in content
    assert "function showVibeFeedback(message, variant = 'warning')" in content
    assert "if (darkMode) {" in content
    assert "button.disabled = darkMode" in content
    assert "vibeSelect.disabled = darkMode" in content
    assert "clearThemeOverrides();" in content
    assert "return;" in content
    assert "applyTheme(startIdx);" in content
    assert (
        "const effectiveIdx = Number.isFinite(requestedIdx) ? requestedIdx : 0;"
        in content
    )
    assert "document.querySelectorAll('[data-vibe-preview-name]')" in content
    assert "document.querySelectorAll('[data-vibe-preview-badge]')" not in content
    assert "document.querySelectorAll('[data-vibe-compatible-chip]')" not in content

    # light-mode branch must still set sane defaults and reset text colors
    assert 'root.style.setProperty("--nav-text", mixHex("#f8fbff"' in content
    assert 'root.style.setProperty("--body-text", mixHex("#132033"' in content

    # banner and other supplemental variables still exist for light mode
    assert 'root.style.setProperty("--banner-bg"' in content
    assert 'root.style.setProperty("--banner-border"' in content
    assert 'root.style.setProperty("--banner-shadow"' in content
