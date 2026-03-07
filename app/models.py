"""Data models for users, requests, artifacts, comments, submissions, and audit trails."""

from datetime import datetime, timedelta
import json
import secrets
from flask_login import UserMixin
from .extensions import db

DEPARTMENTS = ("A", "B", "C")

STATUSES = (
    "NEW_FROM_A",
    "UNDER_REVIEW",
    "B_IN_PROGRESS",
    "WAITING_ON_A_RESPONSE",
    "PENDING_C_REVIEW",
    "EXEC_APPROVAL",
    "C_NEEDS_CHANGES",
    "C_APPROVED",
    "B_FINAL_REVIEW",
    "SENT_TO_A",
    "CLOSED",
)

REQUEST_TYPES = ("part_number", "instructions", "both")
PRIORITIES = ("low", "medium", "high")
PRICEBOOK_LABELS = {
    "in_pricebook": "On the sales list",
    "not_in_pricebook": "Not on the sales list",
    "unknown": "Unknown / needs check",
}

VISIBILITY_SCOPES = (
    "public",
    "dept_a_internal",
    "dept_b_internal",
    "dept_c_internal",
)

ACTION_TYPES = (
    "created",
    "status_change",
    "artifact_added",
    "comment_added",
    "assignment_changed",
    "submission_created",
    "c_review_toggled",
)

class User(db.Model, UserMixin):
    """Application user account (local or SSO-backed)."""
    id = db.Column(db.Integer, primary_key=True)
    sso_sub = db.Column(db.String(255), unique=True, nullable=True, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    department = db.Column(db.String(1), nullable=False, default="A")  # A/B/C
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    # Optional TOTP 2FA for local accounts
    totp_secret = db.Column(db.String(64), nullable=True)
    totp_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Optional per-user vibe/theme preference (index into palettes)
    vibe_index = db.Column(db.Integer, nullable=True, default=0)
    # Persist the last department the user was viewing when they logged out
    # or switched contexts. This is used to restore their active department
    # on subsequent logins when they have multiple department assignments.
    last_active_dept = db.Column(db.String(2), nullable=True)

class Notification(db.Model):
    """In-app notification with optional deep link and dedupe key."""
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", backref="notifications")

    request_id = db.Column(db.Integer, db.ForeignKey("request.id"), nullable=True)
    request = db.relationship("Request")

    type = db.Column(db.String(40), nullable=False)  # e.g. status_change, edit_requested, new_comment
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=True)

    url = db.Column(db.String(500), nullable=True)   # where to click
    dedupe_key = db.Column(db.String(200), nullable=True, index=True)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    read_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class Request(db.Model):
    """Primary work item moving across departments; may be guest-accessible."""
    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(200), nullable=False)
    request_type = db.Column(db.String(30), nullable=False)
    pricebook_status = db.Column(db.String(30), nullable=False, default="unknown")
    # Optional reference identifier when item is on the sales list (e.g., SKU/price id)
    sales_list_reference = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text, nullable=False)
    priority = db.Column(db.String(20), nullable=False)

    # NEW: Optional Dept C review
    requires_c_review = db.Column(db.Boolean, nullable=False, default=False)

    status = db.Column(db.String(40), nullable=False, default="NEW_FROM_A")
    owner_department = db.Column(db.String(1), nullable=False, default="B")
    # Optional chosen workflow for this request (guest or user-created)
    workflow_id = db.Column(db.Integer, db.ForeignKey('workflow.id'), nullable=True)
    workflow = db.relationship('Workflow', backref='requests')

    assigned_to_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    assigned_to_user = db.relationship("User", foreign_keys=[assigned_to_user_id])

    submitter_type = db.Column(db.String(20), nullable=False, default="user")  # user/guest
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_by_user = db.relationship("User", foreign_keys=[created_by_user_id])

    guest_email = db.Column(db.String(255), nullable=True)
    guest_name = db.Column(db.String(120), nullable=True)
    guest_access_token = db.Column(db.String(128), nullable=True, unique=True, index=True)
    guest_token_expires_at = db.Column(db.DateTime, nullable=True)

    due_at = db.Column(db.DateTime, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    artifacts = db.relationship("Artifact", backref="request", lazy=True, cascade="all, delete-orphan")
    comments = db.relationship("Comment", backref="request", lazy=True, cascade="all, delete-orphan")
    audit_logs = db.relationship("AuditLog", backref="request", lazy=True, cascade="all, delete-orphan")
    submissions = db.relationship("Submission", backref="request", lazy=True, cascade="all, delete-orphan")
    # When True, this request was denied (closed via manual deny or
    # automatic denial). Used to expose a persistent "Denied" bucket.
    is_denied = db.Column(db.Boolean, nullable=False, default=False)

    def ensure_guest_token(self, days_valid: int = 30):
        if not self.guest_access_token:
            self.guest_access_token = secrets.token_urlsafe(32)
            self.guest_token_expires_at = datetime.utcnow() + timedelta(days=days_valid)

    @property
    def pricebook_display(self) -> str:
        """User-facing sales list label with safe fallback for unexpected values."""
        return PRICEBOOK_LABELS.get(self.pricebook_status, PRICEBOOK_LABELS["unknown"])

class Artifact(db.Model):
    """Artifacts attached to a request (part numbers or instructions)."""
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("request.id"), nullable=True)

    artifact_type = db.Column(db.String(30), nullable=False)  # part_number / instructions

    donor_part_number = db.Column(db.String(120), nullable=True)
    target_part_number = db.Column(db.String(120), nullable=True)

    no_donor_reason = db.Column(db.String(60), nullable=True)
    instructions_url = db.Column(db.String(800), nullable=True)

    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_by_user = db.relationship("User", foreign_keys=[created_by_user_id])

    created_by_department = db.Column(db.String(1), nullable=False)  # "A" / "B" / "C"
    created_by_guest_email = db.Column(db.String(255), nullable=True)

    # Dept B can request Dept A to edit
    edit_requested = db.Column(db.Boolean, nullable=False, default=False)
    edit_requested_note = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Comment(db.Model):
    """Request discussion entry with scoped visibility."""
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("request.id"), nullable=False)

    author_type = db.Column(db.String(20), nullable=False)  # user/guest
    author_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    author_user = db.relationship("User", foreign_keys=[author_user_id])
    author_guest_email = db.Column(db.String(255), nullable=True)

    visibility_scope = db.Column(db.String(30), nullable=False, default="public")
    body = db.Column(db.Text, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Submission(db.Model):
    """Handoff packet between departments, optionally public to submitter."""
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("request.id"), nullable=False)

    from_department = db.Column(db.String(1), nullable=True)
    to_department = db.Column(db.String(1), nullable=True)

    from_status = db.Column(db.String(40), nullable=True)
    to_status = db.Column(db.String(40), nullable=True)

    summary = db.Column(db.String(200), nullable=True)
    details = db.Column(db.Text, nullable=True)

    is_public_to_submitter = db.Column(db.Boolean, default=False)

    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_by_user = db.relationship("User", foreign_keys=[created_by_user_id])
    created_by_guest_email = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    attachments = db.relationship("Attachment", backref="submission", lazy=True, cascade="all, delete-orphan")

    # Optional fields to support dynamic form submissions (template-driven)
    template_id = db.Column(db.Integer, nullable=True)
    data = db.Column(db.JSON, nullable=True)


class FormTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class FormField(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('form_template.id'), nullable=False)
    template = db.relationship('FormTemplate', backref='fields')
    name = db.Column(db.String(200), nullable=False)
    label = db.Column(db.String(200), nullable=False)
    field_type = db.Column(db.String(50), nullable=False)
    required = db.Column(db.Boolean, nullable=False, default=False)
    verification = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class FormFieldOption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    field_id = db.Column(db.Integer, db.ForeignKey('form_field.id'), nullable=False)
    field = db.relationship('FormField', backref='options')
    value = db.Column(db.String(400), nullable=False)


class DepartmentFormAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('form_template.id'), nullable=False)
    department_name = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class FieldVerification(db.Model):
    """Map a `FormField` to an external verification provider and key.

    This allows admins to point a field at an external system (for example
    an inventory lookup) without hard-coding provider details into the
    `FormField.verification` JSON column. The runtime code prefers the
    `FormField.verification` payload but will fall back to this mapping when
    present. Storing provider and params separately makes migrations and
    connector wiring easier.
    """
    id = db.Column(db.Integer, primary_key=True)
    field_id = db.Column(db.Integer, db.ForeignKey('form_field.id'), nullable=False)
    field = db.relationship('FormField', backref='verifications')
    provider = db.Column(db.String(100), nullable=False)  # e.g. 'inventory'
    external_key = db.Column(db.String(200), nullable=True)  # e.g. 'part_number'
    params = db.Column(db.JSON, nullable=True)  # provider-specific params
    # When True, failures from this verification mapping may trigger an
    # automatic denial (auto-reject) when global auto-reject is enabled.
    triggers_auto_reject = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Attachment(db.Model):
    """Files attached to a submission (e.g., screenshots)."""
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey("submission.id"), nullable=False)

    uploaded_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    uploaded_by_user = db.relationship("User", foreign_keys=[uploaded_by_user_id])
    uploaded_by_guest_email = db.Column(db.String(255), nullable=True)

    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False, unique=True, index=True)
    content_type = db.Column(db.String(80), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SpecialEmailConfig(db.Model):
    """Singleton configuration for special email/autoresponder and nudges."""
    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    help_email = db.Column(db.String(255), nullable=True)
    help_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    request_form_email = db.Column(db.String(255), nullable=True)
    request_form_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    request_form_first_message = db.Column(db.Text, nullable=True)
    request_form_department = db.Column(db.String(2), nullable=False, default='A')
    request_form_field_validation_enabled = db.Column(db.Boolean, nullable=False, default=False)
    request_form_inventory_out_of_stock_notify_enabled = db.Column(db.Boolean, nullable=False, default=False)
    request_form_inventory_out_of_stock_notify_mode = db.Column(db.String(20), nullable=False, default='email')
    request_form_inventory_out_of_stock_message = db.Column(db.Text, nullable=True)
    # When True, the system will automatically close (auto-reject) incoming
    # submissions if a populated part number is confirmed out of stock by the
    # configured `InventoryService`. Admins may toggle this to prevent bottlenecks.
    request_form_auto_reject_oos_enabled = db.Column(db.Boolean, nullable=False, default=False)
    nudge_enabled = db.Column(db.Boolean, nullable=False, default=False)
    nudge_interval_hours = db.Column(db.Integer, nullable=True)
    # Minimum hours after request creation before nudges may start.
    # Defaults to 4 hours; admin may only extend (enforced in admin UI).
    nudge_min_delay_hours = db.Column(db.Integer, nullable=False, default=4)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @classmethod
    def get(cls):
        cfg = cls.query.first()
        if not cfg:
            cfg = cls()
            db.session.add(cfg)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        return cfg


class FeatureFlags(db.Model):
    """Singleton feature flags for admin toggles.

    Use `FeatureFlags.get()` to access the single row.
    """
    id = db.Column(db.Integer, primary_key=True)
    enable_notifications = db.Column(db.Boolean, nullable=False, default=True)
    enable_nudges = db.Column(db.Boolean, nullable=False, default=True)
    allow_user_nudges = db.Column(db.Boolean, nullable=False, default=False)
    vibe_enabled = db.Column(db.Boolean, nullable=False, default=True)
    sso_admin_sync_enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @classmethod
    def get(cls):
        try:
            f = cls.query.first()
        except Exception:
            try:
                from flask import current_app

                current_app.logger.exception("FeatureFlags: DB read failed")
            except Exception:
                pass
            # If the DB schema is out-of-date (column missing) or the DB is
            # otherwise unavailable, return a default in-memory FeatureFlags
            # instance rather than raising and causing a 500 in templates.
            return cls()

        if not f:
            f = cls()
            db.session.add(f)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        return f


class RejectRequestConfig(db.Model):
    """Singleton configuration for assignee-driven request rejection."""
    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    button_label = db.Column(db.String(120), nullable=False, default="Deny Request")
    rejection_message = db.Column(db.Text, nullable=True)
    dept_a_enabled = db.Column(db.Boolean, nullable=False, default=False)
    dept_b_enabled = db.Column(db.Boolean, nullable=False, default=True)
    dept_c_enabled = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @classmethod
    def get(cls):
        cfg = cls.query.first()
        if not cfg:
            cfg = cls()
            db.session.add(cfg)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        return cfg

    def enabled_for_department(self, dept: str) -> bool:
        d = (dept or "").upper()
        if d == "A":
            return bool(self.dept_a_enabled)
        if d == "B":
            return bool(self.dept_b_enabled)
        if d == "C":
            return bool(self.dept_c_enabled)
        return False


class StatusBucket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    department_name = db.Column(db.String(10), nullable=True)
    order = db.Column(db.Integer, nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Optional workflow assigned to this bucket (scoped by department or global)
    workflow_id = db.Column(db.Integer, db.ForeignKey('workflow.id'), nullable=True)
    workflow = db.relationship('Workflow', backref='buckets')
    statuses = db.relationship('BucketStatus', backref='bucket', lazy='dynamic', cascade='all, delete-orphan')


class BucketStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bucket_id = db.Column(db.Integer, db.ForeignKey('status_bucket.id'), nullable=False)
    status_code = db.Column(db.String(80), nullable=False)
    order = db.Column(db.Integer, nullable=False, default=0)

class AuditLog(db.Model):
    """Immutable audit trail for actions on a request."""
    id = db.Column(db.Integer, primary_key=True)
    # Allow NULL for system-level audit entries not tied to a specific request.
    #
    # Rationale: some audit events represent system/admin operations (for
    # example starting/stopping an impersonation session or global config
    # changes) that are not associated with a single `Request`. Making
    # `request_id` nullable allows inserting these rows without a foreign key
    # to a request while still preserving a consistent audit timeline.
    request_id = db.Column(db.Integer, db.ForeignKey("request.id"), nullable=True)

    actor_type = db.Column(db.String(20), nullable=False)  # user/guest/system
    actor_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    actor_user = db.relationship("User", foreign_keys=[actor_user_id])
    actor_label = db.Column(db.String(255), nullable=True)

    action_type = db.Column(db.String(50), nullable=False)
    from_status = db.Column(db.String(40), nullable=True)
    to_status = db.Column(db.String(40), nullable=True)
    note = db.Column(db.Text, nullable=True)

    # human-readable created timestamp (existing)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # explicit event timestamp for audit events (useful for indexing and queries)
    event_ts = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class SiteConfig(db.Model):
    """Singleton site configuration for banner and rolling quotes."""
    id = db.Column(db.Integer, primary_key=True)
    brand_name = db.Column(db.String(120), nullable=True)
    logo_filename = db.Column(db.String(255), nullable=True)
    theme_preset = db.Column(db.String(40), nullable=False, default='default')
    navbar_banner = db.Column(db.String(500), nullable=True)
    show_banner = db.Column(db.Boolean, nullable=False, default=False)
    _rolling_quotes = db.Column("rolling_quotes", db.Text, nullable=True)  # JSON list of strings
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def banner_html(self):
        return self.navbar_banner

    @banner_html.setter
    def banner_html(self, value):
        self.navbar_banner = value

    @property
    def rolling_quotes_enabled(self):
        return self.show_banner

    @rolling_quotes_enabled.setter
    def rolling_quotes_enabled(self, value):
        self.show_banner = bool(value)

    @property
    def rolling_quotes(self):
        if not self._rolling_quotes:
            return []
        try:
            parsed = json.loads(self._rolling_quotes)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass
        # fallback for newline-delimited legacy storage
        return [line.strip() for line in str(self._rolling_quotes).splitlines() if line.strip()]

    @rolling_quotes.setter
    def rolling_quotes(self, value):
        if value is None:
            self._rolling_quotes = None
            return
        if isinstance(value, list):
            cleaned = [str(x).strip() for x in value if str(x).strip()]
            self._rolling_quotes = json.dumps(cleaned)
            return
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                self._rolling_quotes = None
                return
            # accept JSON list or newline-delimited text from admin input
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    cleaned = [str(x).strip() for x in parsed if str(x).strip()]
                    self._rolling_quotes = json.dumps(cleaned)
                    return
            except Exception:
                pass
            cleaned = [line.strip() for line in raw.splitlines() if line.strip()]
            self._rolling_quotes = json.dumps(cleaned)
            return
        self._rolling_quotes = json.dumps([str(value)])

    @classmethod
    def get(cls):
        cfg = cls.query.first()
        if not cfg:
            cfg = cls()
            db.session.add(cfg)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        return cfg


class Department(db.Model):
    """Optional persisted department metadata (code A/B/C and display label)."""
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(2), nullable=False, unique=True, index=True)
    label = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    order = db.Column(db.Integer, nullable=False, default=0)

    @property
    def name(self):
        return self.label

    @name.setter
    def name(self, v):
        self.label = v


class StatusOption(db.Model):
    """Admin-manageable metadata for status selections.

    Each row corresponds to a status code and can control where the
    request should route (target department) and whether notifications
    should be emitted only when the transition results in a department
    transfer.
    """
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(80), nullable=False, unique=True, index=True)
    label = db.Column(db.String(200), nullable=False)
    # optional override for which department will own the request when this
    # status is selected. If null, the application fallbacks are used.
    target_department = db.Column(db.String(2), nullable=True)
    # When true, notifications for this status change will only be sent when
    # the transition also transfers ownership between departments.
    notify_on_transfer_only = db.Column(db.Boolean, nullable=False, default=False)
    # If false, status selection will not trigger notifications at all.
    notify_enabled = db.Column(db.Boolean, nullable=False, default=True)
    # When true, selecting this status requires a screenshot attachment
    # on transitions that would send work back to Dept B (enforced in routes/ui).
    screenshot_required = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Whether this status should produce email deliveries (when mailer/SSO is active)
    email_enabled = db.Column(db.Boolean, nullable=False, default=False)


class Workflow(db.Model):
    """Admin-definable workflow specification.

    Stores an admin-editable JSON `spec` describing steps and transitions.
    This keeps initial implementation flexible and allows a richer editor
    to be added later.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    # Optional department code to scope this workflow (A/B/C) or NULL for global
    department_code = db.Column(db.String(2), nullable=True)
    spec = db.Column(db.JSON, nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class DepartmentEditor(db.Model):
    """Per-department edit privileges assigned to users by admins."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref='dept_editor_roles')
    department = db.Column(db.String(2), nullable=False, index=True)
    can_edit = db.Column(db.Boolean, nullable=False, default=True)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'department', name='uq_user_dept_editor'),)


class UserDepartment(db.Model):
    """Additional department assignments for users.

    This table allows an admin to assign a user to multiple departments
    without changing their primary `User.department` value. The application
    will treat the primary `User.department` as the default and include any
    `UserDepartment` rows when presenting department-switch choices to the
    user.
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref='departments')
    department = db.Column(db.String(2), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'department', name='uq_user_department'),)


class IntegrationConfig(db.Model):
    """Per-department integration configuration for outbound connectors.

    `kind` is one of: 'ticketing', 'webhook', 'inventory', 'verification'.
    `config` holds provider-specific JSON (as text) such as endpoint URLs and tokens.
    """
    id = db.Column(db.Integer, primary_key=True)
    department = db.Column(db.String(2), nullable=False, index=True)
    kind = db.Column(db.String(40), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    config = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('department', 'kind', name='uq_dept_kind'),)


class NotificationRetention(db.Model):
        """Singleton configuration for notification retention and caps.

        - When `retain_until_eod` is True notifications that were read before
            the start of the current UTC day will no longer be shown in the UI.
        - When `clear_after_read_seconds` is set (int >= 0) read notifications
            are retained only for that many seconds after `read_at`.
            A value of 0 means "clear immediately when checked".
        - `max_notifications_per_user` caps how many notifications are stored
            per user; older notifications are removed when the cap is exceeded.
        """
        id = db.Column(db.Integer, primary_key=True)
        retain_until_eod = db.Column(db.Boolean, nullable=False, default=True)
        clear_after_read_seconds = db.Column(db.Integer, nullable=True)  # seconds, nullable if using retain_until_eod
        max_notifications_per_user = db.Column(db.Integer, nullable=False, default=20)
        max_retention_days = db.Column(db.Integer, nullable=False, default=7)
        created_at = db.Column(db.DateTime, default=datetime.utcnow)

        @classmethod
        def get(cls):
                cfg = cls.query.first()
                if not cfg:
                        cfg = cls()
                        db.session.add(cfg)
                        try:
                                db.session.commit()
                        except Exception:
                                db.session.rollback()
                return cfg


class EmailRouting(db.Model):
    """Admin-managed mappings from received mailbox/email to department handlers.

    Multiple rows may exist for the same `recipient_email` to indicate that
    more than one department can handle requests sent to that address. The
    inbound webhook will consult this table to decide which department should
    own a newly-created Request when an email arrives.
    """
    id = db.Column(db.Integer, primary_key=True)
    recipient_email = db.Column(db.String(255), nullable=False, index=True)
    department_code = db.Column(db.String(2), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @classmethod
    def for_recipient(cls, recipient: str):
        if not recipient:
            return []
        try:
            # Match exact or substring to allow mailbox aliases/fwd rules
            like_val = f"%{recipient.strip().lower()}%"
            return cls.query.filter(db.func.lower(cls.recipient_email).like(like_val)).all()
        except Exception:
            try:
                return cls.query.filter_by(recipient_email=recipient.strip().lower()).all()
            except Exception:
                return []