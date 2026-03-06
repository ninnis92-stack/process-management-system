from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, BooleanField, SubmitField, TextAreaField
from wtforms.fields import EmailField
from wtforms.validators import DataRequired, Email, Optional, Length
from wtforms import IntegerField
from flask_wtf.file import FileField, FileAllowed


class AdminCreateUserForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    name = StringField("Display name", validators=[Optional(), Length(max=255)])
    password = PasswordField("Password", validators=[Optional(), Length(min=6)])
    department = SelectField("Department", choices=[("A", "A"), ("B", "B"), ("C", "C")], validators=[DataRequired()])
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Create / Update User")


class AdminSpecialEmailsForm(FlaskForm):
    enable_feature = SelectField(
        "Request-By-Email Feature",
        choices=[("false", "Off"), ("true", "On")],
        validators=[DataRequired()],
    )
    help_email = EmailField("Help Email", validators=[Optional(), Email(), Length(max=255)])
    help_user = SelectField("Help User (SSO)", choices=[], coerce=int, validators=[Optional()])
    request_form_email = EmailField("Request Form Email", validators=[Optional(), Email(), Length(max=255)])
    request_form_user = SelectField("Request Form User (SSO)", choices=[], coerce=int, validators=[Optional()])
    request_form_first_message = TextAreaField("First autoresponder message", validators=[Optional(), Length(max=2000)])
    nudge_enable = SelectField(
        "High-priority nudges",
        choices=[("false", "Off"), ("true", "On")],
        validators=[DataRequired()],
    )
    nudge_interval_hours = IntegerField("Nudge interval (hours)", default=24, validators=[Optional()])
    email_toggle = BooleanField("Enable Email Delivery (runtime override)", default=False)
    ticketing_toggle = BooleanField("Enable Ticketing Integration (runtime override)", default=False)
    inventory_toggle = BooleanField("Enable Inventory Integration (runtime override)", default=False)
    submit = SubmitField("Save Special Emails")


class ThemeForm(FlaskForm):
    name = StringField('Theme name', validators=[DataRequired(), Length(max=120)])
    css = TextAreaField('Custom CSS', validators=[Optional(), Length(max=20000)])
    logo_url = StringField('Logo URL (optional)', validators=[Optional(), Length(max=255)])
    logo_upload = FileField('Upload Logo', validators=[Optional(), FileAllowed(['png','jpg','jpeg','svg'],'Images only')])
    active = BooleanField('Activate theme after saving', default=False)
    submit = SubmitField('Save Theme')


class FormTemplateForm(FlaskForm):
    name = StringField('Template name', validators=[DataRequired(), Length(max=150)])
    description = TextAreaField('Description', validators=[Optional(), Length(max=2000)])
    submit = SubmitField('Save Template')


class FormFieldForm(FlaskForm):
    name = StringField('Field key (internal)', validators=[DataRequired(), Length(max=120)])
    label = StringField('Label', validators=[DataRequired(), Length(max=200)])
    field_type = SelectField('Type', choices=[('text','Text'),('textarea','Text Area'),('select','Select'),('checkbox','Checkbox'),('radio','Radio'),('date','Date'),('file','File')], validators=[DataRequired()])
    required = BooleanField('Required', default=False)
    hint = StringField('Hint / help text', validators=[Optional(), Length(max=300)])
    order = IntegerField('Order', default=0)
    options_csv = StringField('Options (for select/radio) — comma-separated', validators=[Optional(), Length(max=2000)])
    verification_json = TextAreaField('Verification (JSON params)', validators=[Optional(), Length(max=2000)])
    submit = SubmitField('Add Field')


class DepartmentAssignmentForm(FlaskForm):
    department_id = IntegerField('Department id (optional)', validators=[Optional()])
    department_name = StringField('Department name (optional)', validators=[Optional(), Length(max=150)])
    submit = SubmitField('Assign Template')


class VerificationRuleForm(FlaskForm):
    rule_type = SelectField('Rule type', choices=[('external_lookup','External DB Lookup'),('regex','Regex'),('manual_approval','Manual approval')], validators=[DataRequired()])
    params_json = TextAreaField('Parameters (JSON)', validators=[Optional(), Length(max=2000)])
    active = BooleanField('Active', default=True)
    submit = SubmitField('Save Rule')


class BucketForm(FlaskForm):
    name = StringField('Bucket name', validators=[DataRequired(), Length(max=150)])
    department_id = IntegerField('Department id (optional)', validators=[Optional()])
    department_name = StringField('Department name (optional)', validators=[Optional(), Length(max=150)])
    order = IntegerField('Order', default=0)
    active = BooleanField('Active', default=True)
    submit = SubmitField('Save Bucket')


class BucketStatusForm(FlaskForm):
    status_code = StringField('Status code (e.g. NEW_FROM_A)', validators=[DataRequired(), Length(max=80)])
    order = IntegerField('Order', default=0)
    submit = SubmitField('Add Status')


class DepartmentFormAdmin(FlaskForm):
    code = StringField('Department code (short)', validators=[DataRequired(), Length(max=10)])
    name = StringField('Department name', validators=[DataRequired(), Length(max=150)])
    order = IntegerField('Order', default=0)
    active = BooleanField('Active', default=True)
    submit = SubmitField('Save Department')


class SiteConfigForm(FlaskForm):
    banner_html = TextAreaField('Navbar banner (HTML)', validators=[Optional(), Length(max=2000)])
    rolling_enabled = BooleanField('Enable rolling quotes', default=False)
    rolling_csv = TextAreaField('Rolling quotes (one per line)', validators=[Optional(), Length(max=5000)])
    submit = SubmitField('Save Site Config')
