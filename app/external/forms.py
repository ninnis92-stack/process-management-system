from flask_wtf import FlaskForm
from wtforms.***REMOVED***elds import DateTimeLocalField
from wtforms import StringField, TextAreaField, SelectField, BooleanField, IntegerField
from wtforms.validators import DataRequired, Email, Length, ValidationError, Optional
from datetime import datetime, timedelta


class ExternalNewRequestForm(FlaskForm):
    guest_email = StringField("Your Email", validators=[DataRequired(), Email()])
    guest_name = StringField("Your Name (optional)", validators=[Optional(), Length(max=120)])

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

    donor_part_number = StringField("Donor Part Number", validators=[Optional(), Length(max=120)])
    target_part_number = StringField("Target Part Number", validators=[Optional(), Length(max=120)])

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
        "Price Book Status",
        choices=[
            ("in_pricebook", "In price book"),
            ("not_in_pricebook", "Not in price book"),
            ("unknown", "Unknown / needs check"),
        ],
        validators=[DataRequired()],
    )

    due_at = DateTimeLocalField(
        "Due Date (48+ hours required)",
        format="%Y-%m-%dT%H:%M",
        validators=[DataRequired()],
    )

    description = TextAreaField("Description", validators=[Optional(), Length(max=4000)])

    priority = SelectField(
        "Priority",
        choices=[
            ("low", "Low"),
            ("medium", "Medium"),
            ("high", "High"),
        ],
        validators=[DataRequired()],
    )

    # Enforce donor/target rules based on request_type
    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators=extra_validators)
        if not ok:
            return False

        req_type = (self.request_type.data or "").strip()
        donor = (self.donor_part_number.data or "").strip()
        target = (self.target_part_number.data or "").strip()
        reason = (self.no_donor_reason.data or "").strip()

        # Method (stored as "instructions") requires donor + target (and "Both" includes instructions)
        if req_type in ("instructions", "both"):
            if not donor:
                self.donor_part_number.errors.append("Donor part number is required for Method.")
                return False
            if not target:
                self.target_part_number.errors.append("Target part number is required for Method.")
                return False
            if reason == "needs_create":
                self.no_donor_reason.errors.append("This reason only applies to Part Number requests.")
                return False

        # Part Number request: donor required unless reason == needs_create
        if req_type == "part_number":
            if not donor and reason != "needs_create":
                self.donor_part_number.errors.append(
                    "Donor part number is required unless the part number needs to be created."
                )
                return False

            # Optional: if donor is provided, reason should be blank
            if donor and reason:
                self.no_donor_reason.errors.append("Clear the reason if you provide a donor part number.")
                return False

        return True

    def validate_due_at(self, ***REMOVED***eld):
        min_due = datetime.utcnow() + timedelta(hours=48)
        if ***REMOVED***eld.data < min_due:
            raise ValidationError("Due date must be at least 48 hours from now.")


class ExternalCommentForm(FlaskForm):
    body = TextAreaField("Comment", validators=[DataRequired(), Length(max=2000)])


class GuestLookupForm(FlaskForm):
    request_id = IntegerField("Request Number", validators=[DataRequired()])
    guest_email = StringField("Your Email", validators=[DataRequired(), Email()])