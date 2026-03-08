import pytest


def test_no_invert_filter_in_css():
    """Ensure the main stylesheet doesn't rely on CSS filter inversion.

    Historically we used `filter: invert(1)` to flip the close-button icon in
    dark mode, but that approach was brittle (it could accidentally invert
    larger parts of the UI, as reported on /dashboard).  Check the file so we
    don't accidentally reintroduce any `invert(` occurrences.
    """
    path = "app/static/styles.css"
    with open(path, "r") as f:
        content = f.read()
    assert "invert(" not in content, "styles.css should not contain invert filters"
