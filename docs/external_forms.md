External Forms Integration

Overview

This application supports optional integration with third-party form providers (e.g. Microsoft Forms, Google Forms) by directing users to an external form and accepting webhook callbacks that create `Request` and `Submission` records.

How it works

- Admins enable the feature flag `Enable external form integrations` on the Feature Flags page.
- Admins create a Form Template and optionally toggle "Use external form" and provide the external provider name and the external form URL/id.
- When a department is assigned this template, users visiting the New Request page will be redirected or shown a link to the external form instead of the internal form.
- The external provider must be configured to POST form responses to the webhook endpoint in this app: `/integrations/external-form-callback`.
- The webhook uses an HMAC signature in the `X-Webhook-Signature` header (SHA256 hex) which is validated against the shared secret in `WEBHOOK_SHARED_SECRET` app config or environment variable.

Recommended webhook payload

Send JSON with one of the following ways to identify the template:
- `external_form_id`: the provider's form id that you saved in the template (preferred)
- `template_id`: an internal template id (fallback)

Payload example:

{
  "external_form_id": "microsoft-forms-abc123",
  "form_response": {
    "title": "Request for new part",
    "description": "Please create...",
    "priority": "high",
    "request_type": "part_number",
    "donor_part_number": "DON-123",
    "target_part_number": "TGT-456",
    "due_at": "2026-03-10T12:00:00Z"
  }
}

The webhook will map common fields into the created `Request` and store the raw payload in a `Submission` row.

HMAC signing example (Python)

Use the helper script `scripts/generate_webhook_signature.py` to create a SHA256 hex signature for a JSON body using your shared secret.

Security

- Configure `WEBHOOK_SHARED_SECRET` as a strong random string in your deployment environment.
- Only enable `Enable external form integrations` in Feature Flags when you intend to use this feature.

Notes and limitations

- The current implementation performs a best-effort mapping of common fields. If you need stricter validation or custom field mappings, configure the `FormTemplate` and `FormField` definitions in the admin UI and enable strict validation via the inbound-mail feature when applicable.
- Microsoft Forms may not provide direct HMAC signing. If your provider doesn't sign webhooks, configure a proxy or use a middleware that adds the HMAC header. Alternatively, configure the external form to post to a trusted intermediary that re-signs the payload.

Contact

If you want me to add provider-specific parsers (Microsoft Forms native payload mapping) or an example webhook configuration for a specific provider, tell me which provider and I'll add it.
