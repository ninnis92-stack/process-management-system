# Process architecture guide

This app is no longer just a set of route handlers. The long-term process model is split across dedicated service modules so that request intake rules, admin template behavior, and UI behavior can evolve without centralizing all knowledge in one file.

## Main layers

### Route handlers
Route handlers should focus on:
- permission checks
- request/response conversion
- flashing messages
- redirects and template rendering

They should avoid holding most business rules directly.

Primary route modules:
- `app/requests_bp/routes.py`
- `app/admin/routes.py`

### Request intake services
`app/services/request_intake.py` owns request-form orchestration concerns:
- loading the currently assigned request template
- building request template context for rendering
- validating dynamic template submissions
- handling verification-prefill AJAX requests

### Request creation services
`app/services/request_creation.py` owns submission persistence and template-spec shaping:
- building template field specs
- collecting template submission data
- persisting form submissions and attachments
- applying verification-backed prefills to stored submission data

### Requirement rule services
`app/services/requirement_rules.py` is the source of truth for conditional rule behavior:
- rule normalization
- human-readable summaries
- conditional evaluation
- populated-value semantics

All conditional rule changes should be made here first.

### Admin template services
`app/services/template_admin.py` owns template-editor orchestration:
- updating grouped field settings
- grouping fields by section
- building requirement editor context
- parsing and validating admin requirement form input

## Rule model conventions

Conditional requirements are stored as normalized JSON with this shape:

```json
{
  "enabled": true,
  "scope": "field",
  "mode": "all",
  "message": "Optional user-facing explanation",
  "rules": [
    {
      "source_type": "field",
      "source": "request_type",
      "operator": "equals",
      "value": "instructions"
    }
  ]
}
```

### Allowed values
- `scope`: `field`, `section`
- `mode`: `all`, `any`
- `source_type`: `field`, `section`
- `operator`: `populated`, `empty`, `equals`, `not_equals`, `one_of`, `verified`, `any_populated`, `all_populated`

## Maintenance rules

1. Put new process rules in service modules, not large route handlers.
2. Keep admin editing helpers in `template_admin.py`.
3. Keep conditional rule semantics in `requirement_rules.py`.
4. Keep request intake orchestration in `request_intake.py`.
5. Add tests for every new rule operator or branching behavior.

## Recommended next architectural steps

- split `app/requests_bp/routes.py` into focused files for intake, detail, transitions, and dashboards
- split `app/admin/routes.py` into template management, configuration, monitoring, and integrations
- add template versioning and draft/publish workflow
- add typed schemas for admin-managed JSON configuration
