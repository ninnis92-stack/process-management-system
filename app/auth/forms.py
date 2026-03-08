from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, SelectField
from wtforms.validators import DataRequired, Email


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])


class SettingsForm(FlaskForm):
    dark_mode = BooleanField("Enable dark mode")
    vibe_index = SelectField("Theme", coerce=int, choices=[], validate_choice=False)
    quote_set = SelectField("Quote set", coerce=str, choices=[], validate_choice=False)
    quotes_enabled = BooleanField("Show rotating quotes", default=True)
    submit = SubmitField("Save settings")
