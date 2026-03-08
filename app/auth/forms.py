from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, SelectField
from wtforms.validators import DataRequired, Email


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])


class SettingsForm(FlaskForm):
    dark_mode = BooleanField("Enable dark mode")
    vibe_index = SelectField("Theme", coerce=int, choices=[])
    quote_set = SelectField("Quote set", coerce=str, choices=[])
    submit = SubmitField("Save settings")
