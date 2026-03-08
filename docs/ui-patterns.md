# UI patterns guide

This document reduces UI drift by defining shared interaction and presentation rules for admin and request-form screens.

## Shared component rules

### Badge usage
Use the shared `meta_badge()` macro in `app/templates/admin/_macros.html` for lightweight status chips.

Use tones consistently:
- `light`: neutral metadata
- `primary`: automation or system enhancement
- `warning`: conditional or cautionary state
- `success`: completion or healthy state

### Section headings
Use `section_heading()` for major page form sections so titles and supporting text remain consistent.

### Helper cards
Use `helper_card()` when onboarding or guidance text should be visually separated from the form body.

## Form behavior rules

### Request forms
- keep admin-configured fields grouped by section
- prefer inline hints over modal-only explanations
- show active conditional requirement messages near the affected field
- surface progress at the section level for long forms

### Admin forms
- group editable fields by section or responsibility area
- collapse secondary content where possible
- keep advanced JSON editors hidden behind an explicit toggle
- always provide a plain-language path before exposing raw configuration

## Interaction consistency

### Conditional requirement behavior
- show the static summary before activation
- show a stronger live warning when a condition becomes active
- if a custom admin message exists, prefer that message

### Verification-prefill behavior
- show when a field is verification-backed
- show when a field can auto-fill others
- avoid silently overwriting user input unless explicitly allowed

## Review checklist for new screens

Before shipping a new UI flow, verify:
- the page uses shared macros where possible
- helper text explains non-obvious rules
- statuses use consistent badge tones
- long forms have sectioning
- advanced settings are visually separated from common settings
- the screen works without JavaScript for core submission paths
