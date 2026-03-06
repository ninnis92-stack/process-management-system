from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, BooleanField, SubmitField, TextAreaField
from wtforms.fields import EmailField
from wtforms.validators import DataRequired, Email, Optional, Length
from wtforms import IntegerField


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
    submit = SubmitField("Save Special Emails")
