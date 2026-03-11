import json

import re
from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    PasswordField,
    SelectField,
    SelectMultipleField,
    BooleanField,
    SubmitField,
    TextAreaField,
)
from wtforms.fields import EmailField
from wtforms.validators import DataRequired, Email, Optional, Length, URL
from wtforms.validators import AnyOf
from wtforms import ValidationError
from wtforms import IntegerField
from flask_wtf.file import FileField, FileAllowed


class AdminCreateUserForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    name = StringField("Display name", validators=[Optional(), Length(max=255)])
    password = PasswordField("Password", validators=[Optional(), Length(min=6)])
    role = SelectField(
        "Role", choices=[("user", "User"), ("admin", "Admin")], default="user"
    )
    department = SelectField(
        "Department",
        choices=[("A", "A"), ("B", "B"), ("C", "C")],
        validators=[DataRequired()],
    )
    department_override = BooleanField(
        "Admin-managed primary department", default=False
    )
    is_active = BooleanField("Active", default=True)
    is_admin = BooleanField("Admin", default=False)
    # admin may grant a per-user daily reminder allowance (1–5, default 1)
    daily_nudge_limit = IntegerField(
        "Daily reminder limit (1-5)", default=1, validators=[Optional()]
    )

    def validate_daily_nudge_limit(form, field):
        if field.data in (None, ""):
            return
        try:
            iv = int(field.data)
        except Exception:
            raise ValidationError("Must be an integer between 1 and 5")
        if iv < 1 or iv > 5:
            raise ValidationError("Limit must be between 1 and 5")
    # quote preferences for new user
    quote_set = SelectField("Initial quote set", choices=[], validators=[Optional()])
    quotes_enabled = BooleanField("Enable rotating quotes", default=True)
    vibe_button_enabled = BooleanField("Enable vibe button", default=True)
    quote_interval = SelectField(
        "Quote rotation interval", coerce=int, choices=[], validators=[Optional()]
    )
    workflow_role_profile = SelectField(
        "Workflow role profile",
        choices=[
            ("member", "Member"),
            ("coordinator", "Coordinator"),
            ("metrics_lead", "Metrics Lead"),
            ("queue_lead", "Queue Lead"),
        ],
        default="member",
        validators=[Optional()],
    )
    preferred_start_page = SelectField(
        "Preferred start page",
        choices=[
            ("dashboard", "Dashboard"),
            ("search", "Search"),
            ("metrics", "Metrics"),
            ("admin_monitor", "Admin monitor"),
        ],
        default="dashboard",
        validators=[Optional()],
    )
    preferred_start_department = SelectField(
        "Preferred start department",
        choices=[],
        validators=[Optional()],
    )
    watched_departments = SelectMultipleField(
        "Quick-access departments",
        choices=[],
        validators=[Optional()],
    )
    notification_departments = SelectMultipleField(
        "Notification routing departments",
        choices=[],
        validators=[Optional()],
    )
    backup_approver_user_id = SelectField(
        "Backup approver",
        coerce=int,
        choices=[],
        validators=[Optional()],
    )
    submit = SubmitField("Create / Update User")


class SiteConfigForm(FlaskForm):
    QUOTE_MAX_LENGTH = 160
    import_url = StringField(
        "Import branding from website",
        validators=[Optional(), Length(max=255), URL(message="Must be a valid website URL")],
    )
    brand_name = StringField("Brand name", validators=[Optional(), Length(max=120)])
    theme_preset = SelectField(
        "Theme preset",
        choices=[
            ("default", "Default"),
            ("sky", "Sky"),
            ("moss", "Moss"),
            ("dawn", "Dawn"),
            ("twilight", "Twilight"),
        ],
        default="default",
        validators=[Optional()],
    )
    logo_upload = FileField(
        "Logo upload",
        validators=[
            Optional(),
            FileAllowed(["jpg", "jpeg", "png", "webp", "svg"], "Images only"),
        ],
    )
    clear_logo = BooleanField("Remove current logo", default=False)
    navbar_banner = StringField(
        "Navbar banner text", validators=[Optional(), Length(max=500)]
    )
    company_url = StringField(
        "Company URL", validators=[Optional(), Length(max=255), URL(message="Must be a valid URL")] 
    )
    show_banner = BooleanField("Show banner", default=False)
    rolling_quotes = TextAreaField(
        "Rotating quotes (one per line)", validators=[Optional(), Length(max=4000)]
    )
    rolling_quote_sets = TextAreaField(
        "Rolling quote sets (JSON map)", validators=[Optional(), Length(max=8000)]
    )
    active_quote_set = SelectField(
        "Active quote set", choices=[], validators=[Optional()]
    )
    quote_permissions_dept = TextAreaField(
        "Allowed quote sets by department (JSON)", validators=[Optional(), Length(max=4000)]
    )
    quote_permissions_user = TextAreaField(
        "Allowed quote sets by user (JSON)", validators=[Optional(), Length(max=4000)]
    )

    def validate_rolling_quotes(form, field):
        raw = (field.data or "").strip()
        if not raw:
            return
        quotes = [line.strip() for line in raw.splitlines() if line.strip()]
        if len(quotes) > 30:
            raise ValidationError("The default quote set can contain at most 30 quotes.")
        too_long = next((quote for quote in quotes if len(quote) > form.QUOTE_MAX_LENGTH), None)
        if too_long is not None:
            raise ValidationError(
                f"Each quote must be {form.QUOTE_MAX_LENGTH} characters or fewer."
            )

    def validate_rolling_quote_sets(form, field):
        """Validate that `rolling_quote_sets` is a JSON object mapping names to lists of strings."""
        raw = (field.data or "").strip()
        if not raw:
            return
        try:
            import json as _json

            parsed = _json.loads(raw)
        except Exception:
            raise ValidationError("Rolling quote sets must be valid JSON.")
        if not isinstance(parsed, dict):
            raise ValidationError("Rolling quote sets must be a JSON object mapping names to lists.")
        for name, val in parsed.items():
            if not isinstance(name, str) or not name.strip():
                raise ValidationError("Each quote set must have a non-empty name.")
            if not isinstance(val, list):
                raise ValidationError(f"Set '{name}' must be a JSON array of strings.")
            cleaned = [str(item).strip() for item in val if isinstance(item, str) and str(item).strip()]
            if len(cleaned) > 30:
                raise ValidationError(f"Set '{name}' can contain at most 30 quotes.")
            if any(len(item) > form.QUOTE_MAX_LENGTH for item in cleaned):
                raise ValidationError(
                    f"Each quote in '{name}' must be {form.QUOTE_MAX_LENGTH} characters or fewer."
                )
            for item in val:
                if not isinstance(item, str):
                    raise ValidationError(f"All quotes must be strings (error in set '{name}').")

    def _validate_permissions(self, field, kind):
        # helper used by both department and user validators; "self" is the form
        raw = (field.data or "").strip()
        if not raw:
            return
        try:
            import json as _json

            parsed = _json.loads(raw)
        except Exception:
            raise ValidationError(f"{kind} permissions must be valid JSON.")
        if not isinstance(parsed, dict):
            raise ValidationError(f"{kind} permissions must be a JSON object mapping keys to lists.")
        for name, val in parsed.items():
            if not (isinstance(name, str) and name):
                raise ValidationError(f"Invalid key in {kind} permissions: {name}")
            if not isinstance(val, list):
                raise ValidationError(f"Value for '{name}' must be a JSON array.")
            for item in val:
                if not isinstance(item, str):
                    raise ValidationError(f"All entries in {kind} permissions must be strings (error for key '{name}').")

    def validate_quote_permissions_dept(form, field):
        return form._validate_permissions(field, "Department")

    def validate_quote_permissions_user(form, field):
        return form._validate_permissions(field, "User")

    import_branding = SubmitField("Import branding")
    submit = SubmitField("Save site configuration")


class DepartmentForm(FlaskForm):
    code = StringField("Department code", validators=[DataRequired(), Length(max=2)])
    name = StringField("Name", validators=[DataRequired(), Length(max=200)])
    order = IntegerField("Order", default=0, validators=[Optional()])
    active = BooleanField("Active", default=True)
    notification_template = TextAreaField(
        "Notification template",
        description="Optional Jinja2 template applied to notifications sent to users in this department. ``{{ body }}`` and ``{{ title }}`` are available.",
        validators=[Optional()],
    )
    handoff_template_doc_url = StringField(
        "Default handoff doc link",
        validators=[Optional(), Length(max=500)],
    )
    handoff_template_checklist = TextAreaField(
        "Default handoff checklist",
        description="Optional defaults for temporary handoffs in this department. Enter one step per line.",
        validators=[Optional()],
    )
    submit = SubmitField("Save Department")


class SSOAssignForm(FlaskForm):
    emails = TextAreaField(
        "SSO-linked emails (one per line)", validators=[DataRequired()]
    )
    department = SelectField(
        "Assign department",
        choices=[("A", "A"), ("B", "B"), ("C", "C")],
        validators=[DataRequired()],
    )
    submit = SubmitField("Assign")


class StatusOptionForm(FlaskForm):
    code = StringField("Status code", validators=[DataRequired(), Length(max=80)])
    label = StringField("Label", validators=[DataRequired(), Length(max=200)])
    target_department = SelectField(
        "Target department (optional)",
        choices=[("", "-- default --"), ("A", "A"), ("B", "B"), ("C", "C")],
        validators=[Optional()],
    )
    notify_enabled = BooleanField("Enable notifications for this status", default=True)
    notify_on_transfer_only = BooleanField(
        "Only notify when request transfers departments", default=False
    )
    notify_to_originator_only = BooleanField(
        "Notify only request originator (not whole dept)", default=False
    )
    email_enabled = BooleanField(
        "Send email for this status (when mailer/SSO enabled)", default=False
    )
    screenshot_required = BooleanField(
        "Require screenshot when this status sends back to Dept B", default=False
    )
    # new control for automated reminder frequency
    nudge_level = SelectField(
        "Automated reminder level",
        choices=[
            ("0", "None"),
            ("1", "Hourly (1h)"),
            ("2", "Every 4h"),
            ("3", "Once a day"),
        ],
        default="0",
        validators=[Optional()],
    )
    approval_stages_text = TextAreaField(
        "Approval stages",
        validators=[Optional(), Length(max=4000)],
    )
    submit = SubmitField("Save Status")


class DepartmentEditorForm(FlaskForm):
    user_id = SelectField("User", coerce=int, validators=[DataRequired()])
    department = SelectField(
        "Department",
        choices=[("A", "A"), ("B", "B"), ("C", "C")],
        validators=[DataRequired()],
    )
    can_edit = BooleanField("Can edit selections / form fields", default=True)
    can_view_metrics = BooleanField(
        "Department head: can view department metrics", default=False
    )
    can_change_priority = BooleanField(
        "Department head: can change request priority", default=False
    )
    submit = SubmitField("Save Editor")


class IntegrationConfigForm(FlaskForm):
    department = SelectField(
        "Department",
        choices=[("A", "A"), ("B", "B"), ("C", "C")],
        validators=[DataRequired()],
    )
    kind = SelectField(
        "Kind",
        choices=[
            ("ticketing", "Ticketing"),
            ("webhook", "Webhook"),
            ("inventory", "Inventory"),
            ("verification", "Verification"),
        ],
        validators=[DataRequired()],
    )
    enabled = BooleanField("Enabled", default=True)
    config_json = TextAreaField(
        "Config (JSON)", validators=[Optional(), Length(max=4000)]
    )
    submit = SubmitField("Save Integration")


class NotificationRetentionForm(FlaskForm):
    retain_until_eod = BooleanField(
        "Clear read notifications at end of day (UTC)", default=True
    )
    clear_after_choice = SelectField(
        "Clear read after",
        choices=[
            ("eod", "End of day (default)"),
            ("immediate", "When checked (immediately)"),
            ("5m", "5 minutes"),
            ("30m", "30 minutes"),
            ("1h", "1 hour"),
            ("24h", "24 hours"),
            ("custom", "Custom (days)"),
        ],
        default="eod",
    )
    custom_days = IntegerField("Custom days (1-7)", validators=[Optional()])
    max_notifications_per_user = IntegerField("Max notifications per user", default=20)
    submit = SubmitField("Save Retention")


class SpecialEmailConfigForm(FlaskForm):
    enabled = BooleanField("Enable request-by-email feature", default=False)
    request_form_email = StringField(
        "Request form inbox email", validators=[Optional(), Email(), Length(max=255)]
    )
    request_form_user_id = SelectField(
        "Form generation owner (SSO user)", coerce=int, validators=[Optional()]
    )
    request_form_first_message = TextAreaField(
        "First autoresponder message", validators=[Optional(), Length(max=4000)]
    )
    # new options related to email origin and watchers
    request_form_add_original_sender = BooleanField(
        "Record original sender and include in watcher notifications",
        default=False,
    )
    request_form_default_watchers = TextAreaField(
        "Default watcher emails (comma-separated)",
        validators=[Optional(), Length(max=2000)],
        description="Addresses that should always be notified when a request is created via email.",
    )
    request_form_department = SelectField(
        "SSO recognized sender department",
        choices=[("A", "A"), ("B", "B"), ("C", "C")],
        default="A",
    )
    request_form_field_validation_enabled = BooleanField(
        "Enable strict field verification (auto-reject invalid emails)", default=False
    )
    request_form_auto_reject_oos_enabled = BooleanField(
        "Auto-reject when a populated API-verified field is unavailable in the connected system",
        default=False,
    )
    request_form_inventory_out_of_stock_notify_enabled = BooleanField(
        "Notify requester when inventory verification returns out of stock",
        default=False,
    )
    request_form_inventory_out_of_stock_notify_mode = SelectField(
        "Out-of-stock notify mode",
        choices=[
            ("notification", "Notification only"),
            ("email", "Email only"),
            ("both", "Both notification and email"),
        ],
        default="email",
    )
    request_form_inventory_out_of_stock_message = TextAreaField(
        "Auto-reject requester message",
        validators=[Optional(), Length(max=4000)],
    )
    nudge_enabled = BooleanField("Enable reminders", default=False)
    # present a dropdown with a handful of sensible intervals; the stored
    # value is a float representing hours.
    nudge_interval_hours = SelectField(
        "Reminder interval",
        choices=[
            ("0.5", "30 minutes"),
            ("1", "1 hour"),
            ("2", "2 hours"),
            ("4", "4 hours"),
            ("8", "8 hours"),
            ("12", "12 hours"),
            ("24", "24 hours"),
        ],
        default="24",
    )
    nudge_min_delay_hours = IntegerField(
        "Minimum delay before first reminder (hours)", default=4
    )
    submit = SubmitField("Save")


class EmailRoutingForm(FlaskForm):
    recipient_email = StringField(
        "Recipient email", validators=[DataRequired(), Email(), Length(max=255)]
    )
    department_code = SelectField(
        "Department",
        choices=[("A", "A"), ("B", "B"), ("C", "C")],
        validators=[DataRequired()],
    )
    submit = SubmitField("Save Mapping")


class WorkflowForm(FlaskForm):
    name = StringField("Workflow name", validators=[DataRequired(), Length(max=200)])
    description = TextAreaField(
        "Description", validators=[Optional(), Length(max=2000)]
    )
    department_code = SelectField(
        "Department (optional)",
        choices=[("", "-- global --"), ("A", "A"), ("B", "B"), ("C", "C")],
        validators=[Optional()],
    )
    spec_json = TextAreaField(
        "Workflow spec (JSON)", validators=[Optional(), Length(max=20000)]
    )
    active = BooleanField("Active", default=True)
    submit = SubmitField("Save Workflow")


class FormTemplateAdminForm(FlaskForm):
    name = StringField("Template name", validators=[DataRequired(), Length(max=200)])
    description = TextAreaField(
        "Description", validators=[Optional(), Length(max=1000)]
    )
    field_count = IntegerField("Number of fields", default=3)
    verification_prefill_enabled = BooleanField(
        "Allow verified fields to auto-fill linked fields", default=False
    )
    external_enabled = BooleanField(
        "Use external form (e.g. Microsoft Forms)", default=False
    )
    external_provider = StringField(
        "External provider", validators=[Optional(), Length(max=100)]
    )
    external_form_url = StringField(
        "External form URL", validators=[Optional(), Length(max=1000)]
    )
    external_form_id = StringField(
        "External form id", validators=[Optional(), Length(max=255)]
    )
    layout = SelectField(
        "Form layout",
        choices=[("standard", "Standard"), ("compact", "Compact"), ("spacious", "Spacious")],
        default="standard",
        validators=[DataRequired(), AnyOf(["standard", "compact", "spacious"])],
    )
    submit = SubmitField("Create Template")


class FormFieldInlineForm(FlaskForm):
    label = StringField("Field label", validators=[DataRequired(), Length(max=200)])
    name = StringField("Field name/key", validators=[Optional(), Length(max=200)])
    section_name = StringField("Section", validators=[Optional(), Length(max=200)])
    field_type = SelectField(
        "Type",
        choices=[
            ("text", "Text"),
            ("textarea", "Textarea"),
            ("select", "Select"),
            ("file", "File upload"),
            ("photo", "Photo capture"),
            ("video", "Video capture"),
        ],
        default="text",
    )
    required = BooleanField("Required", default=False)
    submit = SubmitField("Save Fields")


class DepartmentAssignmentForm(FlaskForm):
    department = SelectField(
        "Department",
        choices=[("A", "A"), ("B", "B"), ("C", "C")],
        validators=[DataRequired()],
    )
    template_id = SelectField("Template", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Assign Template")


class BulkDepartmentAssignForm(FlaskForm):
    department = SelectField(
        "Department to assign",
        choices=[("A", "A"), ("B", "B"), ("C", "C")],
        validators=[DataRequired()],
    )
    emails = TextAreaField(
        "User emails (one per line or comma-separated)", validators=[DataRequired()]
    )
    submit = SubmitField("Assign Departments")


class FieldVerificationForm(FlaskForm):
    provider = SelectField(
        "Provider",
        choices=[
            ("inventory", "Inventory Service"),
            ("verification", "Realtime tracker / verification integration"),
            ("api", "Legacy verification API"),
        ],
        validators=[DataRequired()],
    )
    external_key = StringField("External key", validators=[Optional(), Length(max=200)])
    verify_each_separated_value = BooleanField(
        "Verify each separated value individually", default=False
    )
    value_separator = StringField(
        "Value separator", validators=[Optional(), Length(max=20)], default="," 
    )
    bulk_input_hint = StringField(
        "User entry hint", validators=[Optional(), Length(max=300)]
    )
    prefill_enabled = BooleanField(
        "Auto-fill linked fields after successful verification", default=False
    )
    prefill_targets_json = TextAreaField(
        "Prefill targets (JSON)", validators=[Optional(), Length(max=3000)]
    )
    prefill_overwrite_existing = BooleanField(
        "Allow verified values to overwrite existing target values", default=False
    )
    params_json = TextAreaField(
        "Params (JSON)", validators=[Optional(), Length(max=2000)]
    )
    triggers_auto_reject = BooleanField(
        "Trigger automatic denial when verification fails", default=False
    )
    submit = SubmitField("Save Verification")


class FieldRequirementForm(FlaskForm):
    enabled = BooleanField("Enable conditional requirement", default=False)
    source_field = SelectField("Trigger field", choices=[], validators=[Optional()])
    operator = SelectField(
        "When",
        choices=[
            ("populated", "Trigger field is populated"),
            ("empty", "Trigger field is empty"),
            ("equals", "Trigger field equals"),
            ("one_of", "Trigger field matches one of these values"),
            ("verified", "Trigger field verifies successfully"),
        ],
        validators=[Optional()],
    )
    expected_value = StringField(
        "Expected value(s)", validators=[Optional(), Length(max=500)]
    )
    message = StringField(
        "User-facing explanation", validators=[Optional(), Length(max=300)]
    )
    submit = SubmitField("Save Requirement Rule")


class FieldRequirementForm(FlaskForm):
    enabled = BooleanField("Enable conditional requirement", default=False)
    scope = SelectField(
        "Apply requirement to",
        choices=[
            ("field", "This field only"),
            ("section", "All fields in this field's section"),
        ],
        default="field",
        validators=[Optional()],
    )
    mode = SelectField(
        "Match mode",
        choices=[("all", "All rules must match"), ("any", "Any rule may match")],
        default="all",
        validators=[Optional()],
    )
    rules_json = TextAreaField(
        "Rules (JSON)", validators=[Optional(), Length(max=5000)]
    )
    message = StringField(
        "User-facing message", validators=[Optional(), Length(max=300)]
    )
    submit = SubmitField("Save Requirement Rules")


class FeatureFlagsForm(FlaskForm):
    enable_notifications = BooleanField("Enable in-app notifications", default=True)
    enable_nudges = BooleanField("Enable automated reminders", default=True)
    allow_user_nudges = BooleanField(
        "Allow users to push reminders to others", default=False
    )
    vibe_enabled = BooleanField("Show Vibe button UI", default=True)
    sso_admin_sync_enabled = BooleanField(
        "Allow SSO to allocate admin access from organization claims/APIs", default=True
    )
    sso_department_sync_enabled = BooleanField(
        "Allow SSO to update primary departments from organization claims/APIs",
        default=False,
    )
    enable_external_forms = BooleanField(
        "Enable external form integrations (3rd-party forms)", default=False
    )
    rolling_quotes_enabled = BooleanField(
        "Enable rolling quotes in the header/footer", default=True
    )
    guest_dashboard_enabled = BooleanField(
        "Enable guest dashboard pages", default=True
    )
    guest_submission_enabled = BooleanField(
        "Enable guest submission page", default=True
    )
    submit = SubmitField("Save Flags")


class MetricsConfigForm(FlaskForm):
    enabled = BooleanField("Enable process metrics tracking", default=True)
    track_request_created = BooleanField("Track request creation events", default=True)
    track_assignments = BooleanField("Track assignment events", default=True)
    track_status_changes = BooleanField("Track status-change events", default=True)
    lookback_days = IntegerField("Default lookback days", default=30)
    user_metrics_limit = IntegerField("Users to show in metrics tables", default=15)
    target_completion_hours = IntegerField("Target completion time (hours)", default=48)
    slow_event_threshold_hours = IntegerField("Slow-event threshold (hours)", default=8)
    submit = SubmitField("Save Metrics Settings")


class GuestFormAdminForm(FlaskForm):
    name = StringField("Guest form name", validators=[DataRequired(), Length(max=200)])
    slug = StringField("Slug (unique)", validators=[DataRequired(), Length(max=200)])
    template_id = SelectField("Template (optional)", coerce=int, validators=[Optional()])
    require_sso = BooleanField("Require SSO-linked account to submit", default=False)
    layout = SelectField(
        "Form layout",
        choices=[("standard", "Standard"), ("compact", "Compact"), ("spacious", "Spacious")],
        default="standard",
        validators=[DataRequired(), AnyOf(["standard", "compact", "spacious"])],
    )
    access_policy = SelectField(
        "Submitter access policy",
        choices=[
            ("public", "Anyone with the form link"),
            ("sso_linked", "Any SSO-linked account"),
            ("approved_sso_domains", "Approved SSO organizations only"),
            ("unaffiliated_only", "Unaffiliated accounts only"),
        ],
        default="public",
        validators=[DataRequired(), AnyOf(["public", "sso_linked", "approved_sso_domains", "unaffiliated_only"])],
    )
    allowed_email_domains = TextAreaField(
        "Approved organization email domains",
        validators=[Optional(), Length(max=4000)],
    )
    credential_requirements_json = TextAreaField(
        "Credential requirements (JSON, reserved for future SSO integrations)",
        validators=[Optional(), Length(max=4000)],
    )
    owner_department = SelectField(
        "Owner department",
        choices=[("A", "A"), ("B", "B"), ("C", "C")],
        default="B",
        validators=[DataRequired()],
    )
    is_default = BooleanField("Set as default guest form", default=False)
    active = BooleanField("Active", default=True)
    submit = SubmitField("Save Guest Form")

    def validate_credential_requirements_json(self, field):
        raw = (field.data or "").strip()
        if not raw:
            return
        try:
            parsed = json.loads(raw)
        except Exception as exc:
            raise ValidationError("Credential requirements must be valid JSON.") from exc
        if not isinstance(parsed, dict):
            raise ValidationError("Credential requirements JSON must be an object.")

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators=extra_validators)
        if not ok:
            return False
        policy = (self.access_policy.data or "public").strip().lower()
        domains = (self.allowed_email_domains.data or "").strip()
        if policy == "approved_sso_domains" and not domains:
            self.allowed_email_domains.errors.append(
                "Add at least one approved organization email domain for this policy."
            )
            return False
        return True


# Tenant- and membership‑related forms for SaaS foundation
class TenantForm(FlaskForm):
    slug = StringField("Slug", validators=[DataRequired(), Length(max=120)])
    name = StringField("Name", validators=[DataRequired(), Length(max=200)])
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save Tenant")


class TenantMembershipForm(FlaskForm):
    user_id = SelectField("User", coerce=int, validators=[DataRequired()])
    role = SelectField(
        "Role",
        choices=[
            ("member", "Member"),
            ("tenant_admin", "Tenant Admin"),
            ("analyst", "Analyst"),
            ("viewer", "Viewer"),
            ("platform_admin", "Platform Admin"),
        ],
        validators=[DataRequired()],
    )
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save Membership")


class RejectRequestConfigForm(FlaskForm):
    enabled = BooleanField("Enable reject request feature", default=True)
    button_label = StringField(
        "Reject button label", validators=[Optional(), Length(max=120)]
    )
    rejection_message = TextAreaField(
        "Message shown with reject action", validators=[Optional(), Length(max=2000)]
    )
    dept_a_enabled = BooleanField("Allow Dept A to reject", default=False)
    dept_b_enabled = BooleanField("Allow Dept B to reject", default=True)
    dept_c_enabled = BooleanField("Allow Dept C to reject", default=False)
    submit = SubmitField("Save Reject Settings")


class StatusBucketForm(FlaskForm):
    name = StringField("Bucket name", validators=[DataRequired(), Length(max=200)])
    department_name = SelectField(
        "Department (optional)",
        choices=[("", "-- global --"), ("A", "A"), ("B", "B"), ("C", "C")],
        validators=[Optional()],
    )
    order = IntegerField("Order", default=0, validators=[Optional()])
    active = BooleanField("Active", default=True)
    workflow_id = SelectField(
        "Assign workflow (optional)", coerce=int, choices=[], validators=[Optional()]
    )
    executive_approval_required = BooleanField("Require executive approval", default=False)
    sales_list_number_required = BooleanField("Require sales list #", default=False)
    bulk_statuses = TextAreaField(
        "Bulk add statuses (one per line)", validators=[Optional()]
    )
    submit = SubmitField("Save Bucket")


class AutomationRuleForm(FlaskForm):
    name = StringField("Rule name", validators=[DataRequired(), Length(max=200)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=2000)])
    triggers = TextAreaField(
        "Triggers",
        description="One event name per line, or '*' to match all events",
        validators=[Optional(), Length(max=2000)],
    )
    conditions = TextAreaField(
        "Conditions (JSON)",
        description='JSON object of simple equality conditions, e.g. {"priority": "high"}',
        validators=[Optional(), Length(max=4000)],
    )
    actions = TextAreaField(
        "Actions (JSON)",
        description='JSON array of action objects, e.g. [{"action": "escalate"}]',
        validators=[Optional(), Length(max=4000)],
    )
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save Rule")
