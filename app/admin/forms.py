from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, BooleanField, SubmitField, TextAreaField
from wtforms.fields import EmailField
from wtforms.validators import DataRequired, Email, Optional, Length
from wtforms.validators import AnyOf
from wtforms import IntegerField
from flask_wtf.file import FileField, FileAllowed


class AdminCreateUserForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    name = StringField("Display name", validators=[Optional(), Length(max=255)])
    password = PasswordField("Password", validators=[Optional(), Length(min=6)])
    department = SelectField("Department", choices=[("A", "A"), ("B", "B"), ("C", "C")], validators=[DataRequired()])
    is_active = BooleanField("Active", default=True)
    is_admin = BooleanField("Admin", default=False)
    submit = SubmitField("Create / Update User")


class SiteConfigForm(FlaskForm):
    brand_name = StringField("Brand name", validators=[Optional(), Length(max=120)])
    theme_preset = SelectField(
        "Theme preset",
        choices=[
            ("default", "Default"),
            ("ocean", "Ocean"),
            ("forest", "Forest"),
            ("sunset", "Sunset"),
            ("midnight", "Midnight"),
        ],
        default="default",
        validators=[Optional()],
    )
    logo_upload = FileField("Logo upload", validators=[Optional(), FileAllowed(["jpg", "jpeg", "png", "webp", "svg"], "Images only")])
    clear_logo = BooleanField("Remove current logo", default=False)
    navbar_banner = StringField("Navbar banner text", validators=[Optional(), Length(max=500)])
    show_banner = BooleanField("Show banner", default=False)
    rolling_quotes = StringField("Rolling quotes (JSON list)", validators=[Optional(), Length(max=4000)])
    submit = SubmitField("Save Site Config")


class DepartmentForm(FlaskForm):
    code = StringField("Department code", validators=[DataRequired(), Length(max=2)])
    name = StringField("Name", validators=[DataRequired(), Length(max=200)])
    order = IntegerField("Order", default=0, validators=[Optional()])
    active = BooleanField("Active", default=True)
    submit = SubmitField("Save Department")


class SSOAssignForm(FlaskForm):
    emails = TextAreaField("SSO-linked emails (one per line)", validators=[DataRequired()])
    department = SelectField("Assign department", choices=[("A", "A"), ("B", "B"), ("C", "C")], validators=[DataRequired()])
    submit = SubmitField("Assign")


class StatusOptionForm(FlaskForm):
    code = StringField("Status code", validators=[DataRequired(), Length(max=80)])
    label = StringField("Label", validators=[DataRequired(), Length(max=200)])
    target_department = SelectField("Target department (optional)", choices=[("", "-- default --"), ("A", "A"), ("B", "B"), ("C", "C")], validators=[Optional()])
    notify_enabled = BooleanField("Enable notifications for this status", default=True)
    notify_on_transfer_only = BooleanField("Only notify when request transfers departments", default=False)
    email_enabled = BooleanField("Send email for this status (when mailer/SSO enabled)", default=False)
    submit = SubmitField("Save Status")


class DepartmentEditorForm(FlaskForm):
    user_id = SelectField("User", coerce=int, validators=[DataRequired()])
    department = SelectField("Department", choices=[("A", "A"), ("B", "B"), ("C", "C")], validators=[DataRequired()])
    can_edit = BooleanField("Can edit selections / form fields", default=True)
    submit = SubmitField("Save Editor")


class IntegrationConfigForm(FlaskForm):
    department = SelectField("Department", choices=[("A", "A"), ("B", "B"), ("C", "C")], validators=[DataRequired()])
    kind = SelectField("Kind", choices=[("ticketing", "Ticketing"), ("webhook", "Webhook"), ("inventory", "Inventory"), ("verification", "Verification")], validators=[DataRequired()])
    enabled = BooleanField("Enabled", default=True)
    config_json = TextAreaField("Config (JSON)", validators=[Optional(), Length(max=4000)])
    submit = SubmitField("Save Integration")


class NotificationRetentionForm(FlaskForm):
    retain_until_eod = BooleanField("Clear read notifications at end of day (UTC)", default=True)
    clear_after_choice = SelectField("Clear read after", choices=[("eod", "End of day (default)"), ("immediate", "When checked (immediately)"), ("5m", "5 minutes"), ("30m", "30 minutes"), ("1h", "1 hour"), ("24h", "24 hours"), ("custom", "Custom (days)")], default="eod")
    custom_days = IntegerField("Custom days (1-7)", validators=[Optional()])
    max_notifications_per_user = IntegerField("Max notifications per user", default=20)
    submit = SubmitField("Save Retention")


class SpecialEmailConfigForm(FlaskForm):
    enabled = BooleanField("Enable request-by-email feature", default=False)
    request_form_email = StringField("Request form inbox email", validators=[Optional(), Email(), Length(max=255)])
    request_form_user_id = SelectField("Form generation owner (SSO user)", coerce=int, validators=[Optional()])
    request_form_first_message = TextAreaField("First autoresponder message", validators=[Optional(), Length(max=4000)])
    request_form_department = SelectField("SSO recognized sender department", choices=[("A", "A"), ("B", "B"), ("C", "C")], default="A")
    request_form_field_validation_enabled = BooleanField("Enable strict field verification (auto-reject invalid emails)", default=False)
    request_form_auto_reject_oos_enabled = BooleanField("Auto-reject when a populated API-verified field is unavailable in the connected system", default=False)
    request_form_inventory_out_of_stock_notify_enabled = BooleanField("Notify requester when inventory verification returns out of stock", default=False)
    request_form_inventory_out_of_stock_notify_mode = SelectField(
        "Out-of-stock notify mode",
        choices=[("notification", "Notification only"), ("email", "Email only"), ("both", "Both notification and email")],
        default="email",
    )
    request_form_inventory_out_of_stock_message = TextAreaField(
        "Auto-reject requester message",
        validators=[Optional(), Length(max=4000)],
    )
    nudge_enabled = BooleanField("Enable nudges", default=False)
    nudge_interval_hours = IntegerField("Nudge interval (hours)", default=24)
    nudge_min_delay_hours = IntegerField("Minimum delay before first nudge (hours)", default=4)
    submit = SubmitField("Save")


class EmailRoutingForm(FlaskForm):
    recipient_email = StringField("Recipient email", validators=[DataRequired(), Email(), Length(max=255)])
    department_code = SelectField("Department", choices=[("A", "A"), ("B", "B"), ("C", "C")], validators=[DataRequired()])
    submit = SubmitField("Save Mapping")


class WorkflowForm(FlaskForm):
    name = StringField("Workflow name", validators=[DataRequired(), Length(max=200)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=2000)])
    department_code = SelectField("Department (optional)", choices=[("", "-- global --"), ("A", "A"), ("B", "B"), ("C", "C")], validators=[Optional()])
    spec_json = TextAreaField("Workflow spec (JSON)", validators=[Optional(), Length(max=20000)])
    active = BooleanField("Active", default=True)
    submit = SubmitField("Save Workflow")


class FormTemplateAdminForm(FlaskForm):
    name = StringField("Template name", validators=[DataRequired(), Length(max=200)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=1000)])
    field_count = IntegerField("Number of fields", default=3)
    submit = SubmitField("Create Template")


class FormFieldInlineForm(FlaskForm):
    label = StringField("Field label", validators=[DataRequired(), Length(max=200)])
    name = StringField("Field name/key", validators=[Optional(), Length(max=200)])
    field_type = SelectField("Type", choices=[("text", "Text"), ("textarea", "Textarea"), ("select", "Select")], default="text")
    required = BooleanField("Required", default=False)
    submit = SubmitField("Save Fields")


class DepartmentAssignmentForm(FlaskForm):
    department = SelectField("Department", choices=[("A", "A"), ("B", "B"), ("C", "C")], validators=[DataRequired()])
    template_id = SelectField("Template", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Assign Template")


class FieldVerificationForm(FlaskForm):
    provider = SelectField("Provider", choices=[('inventory', 'Inventory Service')], validators=[DataRequired()])
    external_key = StringField("External key", validators=[Optional(), Length(max=200)])
    params_json = TextAreaField("Params (JSON)", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Save Verification")


class FeatureFlagsForm(FlaskForm):
    enable_notifications = BooleanField("Enable in-app notifications", default=True)
    enable_nudges = BooleanField("Enable automated nudges", default=True)
    allow_user_nudges = BooleanField("Allow users to push nudges to others", default=False)
    vibe_enabled = BooleanField("Show Vibe button UI", default=True)
    sso_admin_sync_enabled = BooleanField("Allow SSO to allocate admin access from organization claims/APIs", default=True)
    submit = SubmitField("Save Flags")


class RejectRequestConfigForm(FlaskForm):
    enabled = BooleanField("Enable reject request feature", default=True)
    button_label = StringField("Reject button label", validators=[Optional(), Length(max=120)])
    rejection_message = TextAreaField("Message shown with reject action", validators=[Optional(), Length(max=2000)])
    dept_a_enabled = BooleanField("Allow Dept A to reject", default=False)
    dept_b_enabled = BooleanField("Allow Dept B to reject", default=True)
    dept_c_enabled = BooleanField("Allow Dept C to reject", default=False)
    submit = SubmitField("Save Reject Settings")
