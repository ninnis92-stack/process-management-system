from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, BooleanField, SubmitField, TextAreaField
from wtforms.fields import EmailField
from wtforms.validators import DataRequired, Email, Optional, Length


class AdminCreateUserForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    name = StringField("Display name", validators=[Optional(), Length(max=255)])
    password = PasswordField("Password", validators=[Optional(), Length(min=6)])
    department = SelectField("Department", choices=[("A", "A"), ("B", "B"), ("C", "C")], validators=[DataRequired()])
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Create / Update User")


class SiteConfigForm(FlaskForm):
    navbar_banner = StringField("Navbar banner text", validators=[Optional(), Length(max=500)])
    show_banner = BooleanField("Show banner", default=False)
    rolling_quotes = StringField("Rolling quotes (JSON list)", validators=[Optional(), Length(max=4000)])
    submit = SubmitField("Save Site Config")


class DepartmentForm(FlaskForm):
    code = StringField("Department code", validators=[DataRequired(), Length(max=2)])
    label = StringField("Label", validators=[DataRequired(), Length(max=200)])
    description = StringField("Description", validators=[Optional(), Length(max=1000)])
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save Department")


class SSOAssignForm(FlaskForm):
    emails = TextAreaField("SSO-linked emails (one per line)", validators=[DataRequired()])
    department = SelectField("Assign department", choices=[("A", "A"), ("B", "B"), ("C", "C")], validators=[DataRequired()])
    submit = SubmitField("Assign")
