from dataclasses import field

from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    TextAreaField,
    SelectField,
    MultipleFileField,
    BooleanField,
)
from wtforms.fields import DateTimeLocalField
from wtforms.validators import DataRequired, Length, Optional, URL, ValidationError
from datetime import datetime, timedelta


class NewRequestForm(FlaskForm):
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

    due_at = DateTimeLocalField(
        "Due Date (48+ hours required)",
        format="%Y-%m-%dT%H:%M",
        validators=[DataRequired()],
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
    description = TextAreaField("Description", validators=[Optional()])
    priority = SelectField(
        "Priority",
        choices=[
            ("low", "Low"),
            ("medium", "Medium"),
            ("high", "High"),
            ("highest", "Highest"),
        ],
        validators=[DataRequired()],
    )

    def validate_due_at(self, field):
        min_due = datetime.utcnow() + timedelta(hours=48)
        if field.data < min_due:
            raise ValidationError("Due date must be at least 48 hours from now.")

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators=extra_validators)
        if not ok:
            return False

        # Enforce sales_list_reference when Sales List == on the sales list
        try:
            price_sel = (self.pricebook_status.data or "").strip()
        except Exception:
            price_sel = None
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

        # Instructions (Method) require donor + target (and Both includes instructions)
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
            if reason:
                self.no_donor_reason.errors.append(
                    "Reason is only used when no donor is provided for Part Number requests."
                )
                return False

        # Both requires at least donor (target optional)
        if req_type == "both":
            if not donor:
                self.donor_part_number.errors.append(
                    "Donor part number is required for Both."
                )
                return False
            if reason:
                self.no_donor_reason.errors.append(
                    "Reason is not allowed for Both. Provide a donor part number."
                )
                return False

        # Part Number request: donor required unless reason == needs_create
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


class CommentForm(FlaskForm):
    visibility_scope = SelectField(
        "Visibility", choices=[], validators=[DataRequired()]
    )
    body = TextAreaField("Comment", validators=[DataRequired()])


class DonorOnlyForm(FlaskForm):
    donor_part_number = StringField(
        "Donor Part Number", validators=[DataRequired(), Length(max=120)]
    )


class ArtifactForm(FlaskForm):
    artifact_type = SelectField(
        "Artifact Type",
        choices=[
            ("part_number", "Part Number"),
            ("instructions", "Method"),
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
        "If no donor part number, why?",
        choices=[
            ("", "—"),
            ("unknown", "Part number unknown"),
            ("needs_create", "Part number needs to be created"),
        ],
        validators=[Optional()],
    )

    no_donor_reason = SelectField(
        "Reason (if no donor part number)",
        choices=[
            ("", "-- select a reason --"),
            ("part_number_unknown", "Part number unknown"),
            ("part_number_needs_to_be_created", "Part number needs to be created"),
        ],
        validators=[Optional()],
    )

    instructions_url = StringField(
        "Method URL", validators=[Optional(), Length(max=800)]
    )

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators=extra_validators)
        if not ok:
            return False

        t = self.artifact_type.data
        donor = (self.donor_part_number.data or "").strip()
        target = (self.target_part_number.data or "").strip()
        reason = (self.no_donor_reason.data or "").strip()
        url = (self.instructions_url.data or "").strip()

        if t == "part_number":
            # Require target always
            if not target:
                self.target_part_number.errors.append("Target part number is required.")
                return False

            # Donor required OR reason required
            if not donor and not reason:
                self.no_donor_reason.errors.append(
                    "Provide a donor part number or select a reason."
                )
                return False

            # If donor exists, reason must be empty (optional rule, but keeps data clean)
            if donor and reason:
                self.no_donor_reason.errors.append(
                    "Do not select a reason when donor part number is provided."
                )
                return False

            # Instructions URL should not be required/used here
            return True

        if t == "instructions":
            # Require donor and target for Method (stored as "instructions" type)
            if not donor:
                self.donor_part_number.errors.append(
                    "Donor part number is required for method."
                )
                return False
            if not target:
                self.target_part_number.errors.append(
                    "Target part number is required for method."
                )
                return False
            if not url:
                self.instructions_url.errors.append("Method URL is required.")
                return False

            # Validate URL format lightly (WTForms URL validator expects schemes)
            if not (url.startswith("http://") or url.startswith("https://")):
                self.instructions_url.errors.append(
                    "Method URL must start with http:// or https://"
                )
                return False

            # Reason should not be used for Method
            if reason:
                self.no_donor_reason.errors.append(
                    "Reason is only for Part Number artifacts."
                )
                return False

            return True

        self.artifact_type.errors.append("Invalid artifact type.")
        return False


class RequestArtifactEditForm(FlaskForm):
    note = TextAreaField("Edit request note (required)", validators=[DataRequired()])


class TransitionForm(FlaskForm):
    to_status = SelectField("Next Status", choices=[], validators=[DataRequired()])
    target_department = SelectField(
        "Send to department", choices=[], validators=[Optional()]
    )
    submission_summary = StringField("Submission Summary", validators=[Length(max=200)])
    submission_details = TextAreaField("Submission Details")
    files = MultipleFileField("Attachments (images only)")
    requires_c_review = BooleanField("Requires C Review", validators=[Optional()])


class ToggleCReviewForm(FlaskForm):
    reason = TextAreaField("Reason (required)", validators=[DataRequired()])


class AssignmentForm(FlaskForm):
    # Choices injected at runtime per department; -1 means unassigned
    assignee = SelectField("Assign To", choices=[], coerce=int, validators=[Optional()])
