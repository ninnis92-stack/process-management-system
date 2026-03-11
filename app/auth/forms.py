from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])


class SettingsForm(FlaskForm):
    dark_mode = BooleanField("Enable dark mode")
    vibe_index = SelectField("Theme", coerce=int, choices=[], validate_choice=False)
    quote_set = SelectField("Quote set", coerce=str, choices=[], validate_choice=False)
    quotes_enabled = BooleanField("Show rotating quotes", default=True)
    vibe_button_enabled = BooleanField("Show vibe button in navbar", default=True)
    onboarding_guidance_enabled = BooleanField("Show onboarding guidance", default=True)
    # how often (in seconds) the displayed quote should advance
    quote_interval = SelectField(
        "Quote rotation interval", coerce=int, choices=[], validate_choice=False
    )
    submit = SubmitField("Save settings")
