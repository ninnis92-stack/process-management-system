from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, BooleanField, SubmitField
from wtforms.fields import EmailField
from wtforms.validators import DataRequired, Email, Optional, Length


class AdminCreateUserForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    name = StringField("Display name", validators=[Optional(), Length(max=255)])
    password = PasswordField("Password", validators=[Optional(), Length(min=6)])
    department = SelectField("Department", choices=[("A", "A"), ("B", "B"), ("C", "C")], validators=[DataRequired()])
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Create / Update User")
