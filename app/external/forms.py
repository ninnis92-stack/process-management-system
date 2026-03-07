from flask_wtf import FlaskForm
from wtforms.fields import DateTimeLocalField
from wtforms import StringField, TextAreaField, SelectField, BooleanField, IntegerField
from wtforms.validators import DataRequired, Email, Length, ValidationError, Optional
from datetime import datetime, timedelta


class ExternalNewRequestForm(FlaskForm):
    guest_email = StringField("Your Email", validators=[DataRequired(), Email()])
    guest_name = StringField(
        "Your Name (optional)", validators=[Optional(), Length(max=120)]
    )

    owner_department = SelectField(
        "Owner Department",
        choices=[("A", "A"), ("B", "B"), ("C", "C")],
        validators=[Optional()],
    )
    workflow_id = SelectField(
        "Workflow (optional)", coerce=int, choices=[], validators=[Optional()]
    )

    title = StringField("Title", validators=[DataRequired(), Length(max=200)])

    request_type = SelectField(
        "Request Type",
        choices=[
            ("part_number", "Part Number"),
            ("instructions", "Method"),
            ("both", "Both"),
        ],
        validators=[DataRequired()],
    )

    donor_part_number = StringField(
        "Donor Part Number", validators=[Optional(), Length(max=120)]
    )
    target_part_number = StringField(
        "Target Part Number", validators=[Optional(), Length(max=120)]
    )

    no_donor_reason = SelectField(
        "If no donor part number, select a reason",
        choices=[
            ("", "— Select reason —"),
            ("unknown", "Part number unknown"),
            ("needs_create", "Part number needs to be created"),
        ],
        validators=[Optional()],
    )

    pricebook_status = SelectField(
        "Sales List",
        choices=[
            ("in_pricebook", "On the sales list"),
            ("not_in_pricebook", "Not on the sales list"),
            ("unknown", "Unknown / needs check"),
        ],
        validators=[DataRequired()],
    )
    sales_list_reference = StringField(
        "Sales list reference (required if on the sales list)",
        validators=[Optional(), Length(max=200)],
    )

    due_at = DateTimeLocalField(
        "Due Date (48+ hours required)",
        format="%Y-%m-%dT%H:%M",
        validators=[DataRequired()],
    )

    description = TextAreaField(
        "Description", validators=[Optional(), Length(max=4000)]
    )

    priority = SelectField(
        "Priority",
        choices=[
            ("low", "Low"),
            ("medium", "Medium"),
            ("high", "High"),
        ],
        validators=[DataRequired()],
    )

    # Enforce donor/target rules based on request_type and sales list reference
    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators=extra_validators)
        if not ok:
            return False

        # Enforce sales_list_reference when Sales List == on the sales list
        price_sel = (self.pricebook_status.data or "").strip()
        ref = (
            (getattr(self, "sales_list_reference", None).data or "").strip()
            if getattr(self, "sales_list_reference", None)
            else ""
        )
        if price_sel == "in_pricebook" and not ref:
            if getattr(self, "sales_list_reference", None):
                self.sales_list_reference.errors.append(
                    "Sales list reference is required when item is on the sales list."
                )
            return False

        req_type = (self.request_type.data or "").strip()
        donor = (self.donor_part_number.data or "").strip()
        target = (self.target_part_number.data or "").strip()
        reason = (self.no_donor_reason.data or "").strip()

        # Method (stored as "instructions") requires donor + target.
        if req_type == "instructions":
            if not donor:
                self.donor_part_number.errors.append(
                    "Donor part number is required for Method."
                )
                return False
            if not target:
                self.target_part_number.errors.append(
                    "Target part number is required for Method."
                )
                return False
            if reason == "needs_create":
                self.no_donor_reason.errors.append(
                    "This reason only applies to Part Number requests."
                )
                return False

        if req_type == "both":
            if not donor:
                self.donor_part_number.errors.append(
                    "Donor part number is required for Both."
                )
                return False
            if reason:
                self.no_donor_reason.errors.append(
                    "This reason is only valid for Part Number requests. Provide a donor part number instead."
                )
                return False

        if req_type == "part_number":
            if not donor and reason != "needs_create":
                self.donor_part_number.errors.append(
                    "Donor part number is required unless the part number needs to be created."
                )
                return False
            if donor and reason:
                self.no_donor_reason.errors.append(
                    "Clear the reason if you provide a donor part number."
                )
                return False

        return True

    def validate_due_at(self, field):
        min_due = datetime.utcnow() + timedelta(hours=48)
        if field.data < min_due:
            raise ValidationError("Due date must be at least 48 hours from now.")


class ExternalCommentForm(FlaskForm):
    body = TextAreaField("Comment", validators=[DataRequired(), Length(max=2000)])


class GuestLookupForm(FlaskForm):
    # Allow guests to either lookup a single request by id+email or
    # provide just their email to list all their open requests.
    request_id = IntegerField("Request Number", validators=[Optional()])
    guest_email = StringField("Your Email", validators=[DataRequired(), Email()])
