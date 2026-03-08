import pytest


def test_dark_mode_palette_values():
    """Ensure the dark-mode section of styles.css matches the new palette."""
    path = "app/static/styles.css"
    with open(path, "r") as f:
        content = f.read()
    # check main variables
    assert "--page-bg: #121212" in content
    assert "--surface: #1e1e1e" in content
    assert "--nav-bg: #202124" in content
    # ensure panel backgrounds use var(--surface)
    assert "dark-mode .page-header" in content
    panel_rule = [line for line in content.splitlines() if "dark-mode .page-header" in line]
    assert panel_rule, "no panel rule found"
    # verify var(--surface) in the rule block
    assert "var(--surface)" in content
