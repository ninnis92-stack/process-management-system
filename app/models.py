"""Data models for users, requests, artifacts, comments, submissions, and audit trails."""

from datetime import datetime, timedelta
import secrets
from flask_login import UserMixin
from .extensions import db

DEPARTMENTS = ("A", "B", "C")

STATUSES = (
    "NEW_FROM_A",
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
    "in_pricebook": "On sales list",
    "not_in_pricebook": "Not on sales list",
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
    # Timestamp when the notification was marked read (used for daily clearing)
    read_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class Request(db.Model):
    """Primary work item moving across departments; may be guest-accessible."""
    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(200), nullable=False)
    request_type = db.Column(db.String(30), nullable=False)
    pricebook_status = db.Column(db.String(30), nullable=False, default="unknown")
    description = db.Column(db.Text, nullable=False)
    priority = db.Column(db.String(20), nullable=False)

    # NEW: Optional Dept C review
    requires_c_review = db.Column(db.Boolean, nullable=False, default=False)

    status = db.Column(db.String(40), nullable=False, default="NEW_FROM_A")
    owner_department = db.Column(db.String(1), nullable=False, default="B")

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

    from_department = db.Column(db.String(1), nullable=False)
    to_department = db.Column(db.String(1), nullable=False)

    from_status = db.Column(db.String(40), nullable=False)
    to_status = db.Column(db.String(40), nullable=False)

    summary = db.Column(db.String(200), nullable=False)
    details = db.Column(db.Text, nullable=False)

    is_public_to_submitter = db.Column(db.Boolean, default=False)

    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_by_user = db.relationship("User", foreign_keys=[created_by_user_id])
    created_by_guest_email = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    attachments = db.relationship("Attachment", backref="submission", lazy=True, cascade="all, delete-orphan")

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


class SpecialEmailConfig(db.Model):
    """Singleton-style table to store admin-configured special emails and behavior.

    Fields:
      - enabled: whether the request-by-email feature is active
      - help_email: designated email for help requests
      - request_form_email: email address that acts as a request form inbox
      - request_form_first_message: initial autoresponder message body
    """
    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    help_email = db.Column(db.String(255), nullable=True)
    request_form_email = db.Column(db.String(255), nullable=True)
    request_form_first_message = db.Column(db.Text, nullable=True)
    help_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    help_user = db.relationship("User", foreign_keys=[help_user_id])
    request_form_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    request_form_user = db.relationship("User", foreign_keys=[request_form_user_id])

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