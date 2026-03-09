import pytest


def test_dark_mode_palette_values():
    """Ensure the dark-mode section of styles.css matches the new palette."""
    path = "app/static/styles.css"
    with open(path, "r") as f:
        content = f.read()
    # check main variables
    assert "--page-bg: radial-gradient(circle at 18% 18%, rgba(125, 211, 252, 0.10), transparent 30%)" in content
    assert "--surface: #111c2d" in content
    assert "--surface-2: #18263b" in content
    assert "--nav-bg: #0b1220" in content
    # dark-mode should explicitly set nav-text as well
    assert "--nav-text: #e8f0fb" in content
    # ensure there is a default (light) value too so the navbar text
    # remains visible on a typically dark background (themes assume dark
    # nav bars).  light default happens to be the same value login pages use.
    assert "--nav-text: #f8fbff" in content
    # body text should default to a dark color as well
    assert "--body-text: #132033" in content
    # the banner quote should derive its color from nav-text rather than
    # being hard-coded white so it works in light mode
    import re
    match = re.search(r"\.brand-quote\s*\{[^}]*var\(--nav-text\)", content)
    assert match, "default .brand-quote rule must use var(--nav-text)"
    assert re.search(r"#motivation\s*\{[^}]*var\(--nav-text\)", content), "#motivation should use nav text color"
    # ensure panel backgrounds use var(--surface)
    assert "dark-mode .page-header" in content
    panel_rule = [line for line in content.splitlines() if "dark-mode .page-header" in line]
    assert panel_rule, "no panel rule found"
    # verify var(--surface) in the rule block
    assert "var(--surface)" in content
