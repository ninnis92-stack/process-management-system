from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, BooleanField, SubmitField, TextAreaField, IntegerField
from wtforms.fields import EmailField
from wtforms.validators import DataRequired, Email, Optional, Length, NumberRange


class AdminCreateUserForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    name = StringField("Display name", validators=[Optional(), Length(max=255)])
    password = PasswordField("Password", validators=[Optional(), Length(min=6)])
    department = SelectField("Department", choices=[("A", "A"), ("B", "B"), ("C", "C")], validators=[DataRequired()])
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Create / Update User")


class ProcessGroupForm(FlaskForm):
    name = StringField("Group name", validators=[DataRequired(), Length(max=120)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=1000)])
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save Group")


class ProcessStepForm(FlaskForm):
    label = StringField("Step label", validators=[DataRequired(), Length(max=120)])
    department = SelectField(
        "Responsible department",
        choices=[("A", "Department A"), ("B", "Department B"), ("C", "Department C")],
        validators=[DataRequired()],
    )
    description = TextAreaField("Description / notes", validators=[Optional(), Length(max=500)])
    step_order = IntegerField("Order", default=0, validators=[NumberRange(min=0)])
    submit = SubmitField("Add Step")
