from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, SelectMultipleField, BooleanField, SubmitField, IntegerField
from wtforms.fields import EmailField
from wtforms.validators import DataRequired, Email, Optional, Length


class AdminCreateUserForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    name = StringField("Display name", validators=[Optional(), Length(max=255)])
    password = PasswordField("Password", validators=[Optional(), Length(min=6)])
    department = SelectField("Department", choices=[("A", "A"), ("B", "B"), ("C", "C")], validators=[DataRequired()])
    department_memberships = SelectMultipleField(
        "Additional Departments",
        choices=[("A", "A"), ("B", "B"), ("C", "C")],
        validators=[Optional()],
    )
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Create / Update User")


class FlowGroupForm(FlaskForm):
    name = StringField("Group name", validators=[DataRequired(), Length(max=120)])
    description = StringField("Description", validators=[Optional(), Length(max=500)])
    is_active = BooleanField("Active", default=True)
    is_default = BooleanField("Default group", default=False)
    submit = SubmitField("Save Flow Group")


class FlowStepForm(FlaskForm):
    name = StringField("Step label", validators=[Optional(), Length(max=120)])
    sort_order = IntegerField("Order", validators=[DataRequired()])

    actor_department = SelectField(
        "Actor Department",
        choices=[("A", "A"), ("B", "B"), ("C", "C")],
        validators=[DataRequired()],
    )
    from_status = StringField("From Status", validators=[DataRequired(), Length(max=40)])
    to_status = StringField("To Status", validators=[DataRequired(), Length(max=40)])

    from_department = SelectField(
        "From Department",
        choices=[("", "Auto"), ("A", "A"), ("B", "B"), ("C", "C")],
        validators=[Optional()],
    )
    to_department = SelectField(
        "To Department",
        choices=[("", "Auto"), ("A", "A"), ("B", "B"), ("C", "C")],
        validators=[Optional()],
    )

    requires_submission = BooleanField("Requires submission payload", default=False)
    submit = SubmitField("Save Step")


class ProcessStatusForm(FlaskForm):
    code = StringField("Status Code", validators=[DataRequired(), Length(max=40)])
    label = StringField("Display Label", validators=[DataRequired(), Length(max=120)])
    description = StringField("Description", validators=[Optional(), Length(max=500)])

    behavior = SelectField(
        "Behavior",
        choices=[
            ("status_only", "Update status only"),
            ("transfer", "Update status and transfer request"),
        ],
        validators=[DataRequired()],
    )
    transfer_to_department = SelectField(
        "Transfer To Department",
        choices=[("", "None"), ("A", "A"), ("B", "B"), ("C", "C")],
        validators=[Optional()],
    )
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save Status")
