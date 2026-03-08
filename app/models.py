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


TENANT_ROLES = (
    "platform_admin",
    "tenant_admin",
    "analyst",
    "member",
    "viewer",
)


class TenantScopedMixin:
    """Mixin for records that belong to a single tenant."""

    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=True, index=True)


class SubscriptionPlan(db.Model):
    """Commercial plan metadata and configurable limits."""

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), nullable=False, unique=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    max_users = db.Column(db.Integer, nullable=False, default=25)
    max_requests_per_month = db.Column(db.Integer, nullable=False, default=2000)
    max_departments = db.Column(db.Integer, nullable=False, default=10)
    feature_flags_json = db.Column(db.JSON, nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @classmethod
    def get_default(cls):
        plan = cls.query.filter_by(code="growth").first()
        if plan:
            return plan
        plan = cls(
            code="growth",
            name="Growth",
            description="Default internal SaaS plan for workflow teams.",
            max_users=50,
            max_requests_per_month=5000,
            max_departments=12,
            feature_flags_json={
                "custom_branding": True,
                "workflow_builder": True,
                "audit_exports": True,
                "event_outbox": True,
            },
        )
        db.session.add(plan)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        return plan


class Tenant(db.Model):
    """Top-level customer account / workspace boundary."""

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(120), nullable=False, unique=True, index=True)
    name = db.Column(db.String(200), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey("subscription_plan.id"), nullable=True)
    plan = db.relationship("SubscriptionPlan", backref="tenants")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @classmethod
    def get_default(cls):
        tenant = cls.query.filter_by(slug="default").first()
        if tenant:
            return tenant
        tenant = cls(name="Default Workspace", slug="default")
        db.session.add(tenant)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        return tenant


class TenantMembership(db.Model):
    """Maps users to tenants with an explicit SaaS role."""

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=False, index=True)
    tenant = db.relationship("Tenant", backref="memberships")
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    user = db.relationship("User", backref="tenant_memberships", foreign_keys=[user_id])
    role = db.Column(db.String(40), nullable=False, default="member")
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_user_membership"),
    )


class JobRecord(TenantScopedMixin, db.Model):
    """Persistent job ledger for reliable background work and observability."""

    id = db.Column(db.Integer, primary_key=True)
    job_name = db.Column(db.String(120), nullable=False, index=True)
    queue_name = db.Column(db.String(80), nullable=False, default="default")
    status = db.Column(db.String(30), nullable=False, default="queued", index=True)
    payload_json = db.Column(db.JSON, nullable=True)
    result_json = db.Column(db.JSON, nullable=True)
    error_text = db.Column(db.Text, nullable=True)
    retry_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)


class IntegrationEvent(TenantScopedMixin, db.Model):
    """Outbound integration boundary event retained even before providers are connected."""

    id = db.Column(db.Integer, primary_key=True)
    event_name = db.Column(db.String(120), nullable=False, index=True)
    destination_kind = db.Column(db.String(60), nullable=False, default="outbox")
    status = db.Column(db.String(30), nullable=False, default="pending", index=True)
    payload_json = db.Column(db.JSON, nullable=True)
    metadata_json = db.Column(db.JSON, nullable=True)
    last_error = db.Column(db.Text, nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class User(TenantScopedMixin, db.Model, UserMixin):
    """Application user account (local or SSO-backed)."""

    # relationship mapping to the Tenant record; explicit primaryjoin is
    # required because the tenant_id column comes from the mixin rather than
    # being defined directly on `User`.
    tenant = db.relationship(
        "Tenant",
        primaryjoin="Tenant.id==User.tenant_id",
        foreign_keys="[User.tenant_id]",
        uselist=False,
    )

    id = db.Column(db.Integer, primary_key=True)
    sso_sub = db.Column(db.String(255), unique=True, nullable=True, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    department = db.Column(db.String(1), nullable=False, default="A")  # A/B/C
    department_override = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    # Optional TOTP 2FA for local accounts
    totp_secret = db.Column(db.String(64), nullable=True)
    totp_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Optional per-user vibe/theme preference (index into palettes)
    vibe_index = db.Column(db.Integer, nullable=True, default=0)
    # User preference: enable dark mode in the UI
    dark_mode = db.Column(db.Boolean, nullable=False, default=False)
    # user preference: quote set for rolling quotes (matches keys of
    # SiteConfig.DEFAULT_QUOTE_SETS).
    quote_set = db.Column(db.String(80), nullable=True)
    # user preference: whether rotating quotes should appear on their dashboard
    quotes_enabled = db.Column(db.Boolean, nullable=False, default=True)
    # Persist the last department the user was viewing when they logged out
    # or switched contexts. This is used to restore their active department
    # on subsequent logins when they have multiple department assignments.
    last_active_dept = db.Column(db.String(2), nullable=True)


class Notification(TenantScopedMixin, db.Model):
    """In-app notification with optional deep link and dedupe key."""

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", backref="notifications")

    request_id = db.Column(db.Integer, db.ForeignKey("request.id"), nullable=True)
    request = db.relationship("Request")

    type = db.Column(
        db.String(40), nullable=False
    )  # e.g. status_change, edit_requested, new_comment
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=True)

    url = db.Column(db.String(500), nullable=True)  # where to click
    dedupe_key = db.Column(db.String(200), nullable=True, index=True)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    read_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class WebhookSubscription(TenantScopedMixin, db.Model):
    """Outgoing webhook destinations registered by external systems."""

    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(2048), nullable=False)
    # list of event names (e.g. ["request.created", "status.changed"])
    events = db.Column(db.JSON, nullable=False, default=list)
    # optional shared secret used to HMAC-sign payloads
    secret = db.Column(db.String(255), nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ProcessMetricEvent(TenantScopedMixin, db.Model):
    """Normalized process analytics event for request lifecycle tracking."""

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("request.id"), nullable=False, index=True)
    request = db.relationship("Request", backref="process_metric_events")

    actor_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    actor_user = db.relationship("User", foreign_keys=[actor_user_id])

    actor_department = db.Column(db.String(2), nullable=True, index=True)
    owner_department = db.Column(db.String(2), nullable=True, index=True)
    event_type = db.Column(db.String(64), nullable=False, index=True)
    from_status = db.Column(db.String(40), nullable=True)
    to_status = db.Column(db.String(40), nullable=True)
    assigned_to_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    assigned_to_user = db.relationship("User", foreign_keys=[assigned_to_user_id])

    # time between this event and the previous tracked event on the request
    since_last_event_seconds = db.Column(db.Integer, nullable=True)
    # total request age at the time of this event
    request_age_seconds = db.Column(db.Integer, nullable=True)

    metadata_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class MetricsConfig(TenantScopedMixin, db.Model):
    """Singleton configuration for process and user-efficiency metrics."""

    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    track_request_created = db.Column(db.Boolean, nullable=False, default=True)
    track_assignments = db.Column(db.Boolean, nullable=False, default=True)
    track_status_changes = db.Column(db.Boolean, nullable=False, default=True)
    lookback_days = db.Column(db.Integer, nullable=False, default=30)
    user_metrics_limit = db.Column(db.Integer, nullable=False, default=15)
    target_completion_hours = db.Column(db.Integer, nullable=False, default=48)
    slow_event_threshold_hours = db.Column(db.Integer, nullable=False, default=8)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    @classmethod
    def get(cls):
        try:
            cfg = cls.query.first()
        except Exception:
            try:
                db.session.rollback()
                cfg = cls.query.first()
            except Exception:
                cfg = None
        if not cfg:
            cfg = cls()
            db.session.add(cfg)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        return cfg


class Request(TenantScopedMixin, db.Model):
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
    workflow_id = db.Column(db.Integer, db.ForeignKey("workflow.id"), nullable=True)
    workflow = db.relationship("Workflow", backref="requests")

    assigned_to_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    assigned_to_user = db.relationship("User", foreign_keys=[assigned_to_user_id])

    submitter_type = db.Column(
        db.String(20), nullable=False, default="user"
    )  # user/guest
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_by_user = db.relationship("User", foreign_keys=[created_by_user_id])

    guest_email = db.Column(db.String(255), nullable=True)
    guest_name = db.Column(db.String(120), nullable=True)
    guest_access_token = db.Column(
        db.String(128), nullable=True, unique=True, index=True
    )
    guest_token_expires_at = db.Column(db.DateTime, nullable=True)

    due_at = db.Column(db.DateTime, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    artifacts = db.relationship(
        "Artifact", backref="request", lazy=True, cascade="all, delete-orphan"
    )
    comments = db.relationship(
        "Comment", backref="request", lazy=True, cascade="all, delete-orphan"
    )
    audit_logs = db.relationship(
        "AuditLog", backref="request", lazy=True, cascade="all, delete-orphan"
    )
    submissions = db.relationship(
        "Submission", backref="request", lazy=True, cascade="all, delete-orphan"
    )
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

    artifact_type = db.Column(
        db.String(30), nullable=False
    )  # part_number / instructions

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
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


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

    attachments = db.relationship(
        "Attachment", backref="submission", lazy=True, cascade="all, delete-orphan"
    )

    # Optional fields to support dynamic form submissions (template-driven)
    template_id = db.Column(db.Integer, nullable=True)
    data = db.Column(db.JSON, nullable=True)


class FormTemplate(TenantScopedMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # When enabled, verification-backed fields on this template may populate
    # other fields in the same request form based on admin-configured mapping.
    verification_prefill_enabled = db.Column(
        db.Boolean, nullable=False, default=False
    )
    # Optional external form integration (eg. Microsoft Forms) — disabled by default
    external_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Provider identifier (informational), e.g. 'microsoft_forms'
    external_provider = db.Column(db.String(100), nullable=True)
    # Full URL to the external form (where users should be sent)
    external_form_url = db.Column(db.String(1000), nullable=True)
    # Optional external provider form id / token
    external_form_id = db.Column(db.String(255), nullable=True)


class GuestForm(TenantScopedMixin, db.Model):
    """Admin-manageable guest form instance used for public/guest submissions.

    Allows per-form toggles such as requiring an SSO-linked account to submit.
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), nullable=False, unique=True, index=True)
    template_id = db.Column(db.Integer, db.ForeignKey("form_template.id"), nullable=True)
    template = db.relationship("FormTemplate", backref="guest_forms")
    require_sso = db.Column(db.Boolean, nullable=False, default=False)
    owner_department = db.Column(db.String(2), nullable=False, default="B")
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class FormField(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(
        db.Integer, db.ForeignKey("form_template.id"), nullable=False
    )
    template = db.relationship("FormTemplate", backref="fields")
    name = db.Column(db.String(200), nullable=False)
    label = db.Column(db.String(200), nullable=False)
    field_type = db.Column(db.String(50), nullable=False)
    required = db.Column(db.Boolean, nullable=False, default=False)
    order = db.Column(db.Integer, nullable=False, default=0)
    hint = db.Column(db.String(300), nullable=True)
    verification = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class FormFieldOption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    field_id = db.Column(db.Integer, db.ForeignKey("form_field.id"), nullable=False)
    field = db.relationship("FormField", backref="options")
    value = db.Column(db.String(400), nullable=False)
    label = db.Column(db.String(200), nullable=True)
    order = db.Column(db.Integer, nullable=False, default=0)


class DepartmentFormAssignment(TenantScopedMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(
        db.Integer, db.ForeignKey("form_template.id"), nullable=False
    )
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
    field_id = db.Column(db.Integer, db.ForeignKey("form_field.id"), nullable=False)
    field = db.relationship("FormField", backref="verifications")
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
    submission_id = db.Column(
        db.Integer, db.ForeignKey("submission.id"), nullable=False
    )

    uploaded_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    uploaded_by_user = db.relationship("User", foreign_keys=[uploaded_by_user_id])
    uploaded_by_guest_email = db.Column(db.String(255), nullable=True)

    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False, unique=True, index=True)
    content_type = db.Column(db.String(80), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SpecialEmailConfig(TenantScopedMixin, db.Model):
    """Singleton configuration for special email/autoresponder and nudges."""

    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    help_email = db.Column(db.String(255), nullable=True)
    help_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    request_form_email = db.Column(db.String(255), nullable=True)
    request_form_user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=True
    )
    request_form_first_message = db.Column(db.Text, nullable=True)
    request_form_department = db.Column(db.String(2), nullable=False, default="A")
    request_form_field_validation_enabled = db.Column(
        db.Boolean, nullable=False, default=False
    )
    request_form_inventory_out_of_stock_notify_enabled = db.Column(
        db.Boolean, nullable=False, default=False
    )
    request_form_inventory_out_of_stock_notify_mode = db.Column(
        db.String(20), nullable=False, default="email"
    )
    request_form_inventory_out_of_stock_message = db.Column(db.Text, nullable=True)
    # When True, the system will automatically close (auto-reject) incoming
    # submissions if a populated part number is confirmed out of stock by the
    # configured `InventoryService`. Admins may toggle this to prevent bottlenecks.
    request_form_auto_reject_oos_enabled = db.Column(
        db.Boolean, nullable=False, default=False
    )
    nudge_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # configurable interval (in hours) between reminder nudges; supports
    # fractional values like 0.5 for thirty minutes so admin can choose finer
    # grained timers. Stored as a float so the database can represent halves.
    nudge_interval_hours = db.Column(db.Float, nullable=True)
    # Minimum hours after request creation before nudges may start.
    # Defaults to 4 hours; admin may only extend (enforced in admin UI).
    nudge_min_delay_hours = db.Column(db.Integer, nullable=False, default=4)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @classmethod
    def get(cls):
        try:
            cfg = cls.query.first()
        except Exception:
            try:
                db.session.rollback()
                cfg = cls.query.first()
            except Exception:
                cfg = None
        if not cfg:
            cfg = cls()
            db.session.add(cfg)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        return cfg


class FeatureFlags(TenantScopedMixin, db.Model):
    """Singleton feature flags for admin toggles.

    Use `FeatureFlags.get()` to access the single row.
    """

    id = db.Column(db.Integer, primary_key=True)
    enable_notifications = db.Column(db.Boolean, nullable=False, default=True)
    enable_nudges = db.Column(db.Boolean, nullable=False, default=True)
    allow_user_nudges = db.Column(db.Boolean, nullable=False, default=False)
    vibe_enabled = db.Column(db.Boolean, nullable=False, default=True)
    sso_admin_sync_enabled = db.Column(db.Boolean, nullable=False, default=True)
    sso_department_sync_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Allow admins to enable external form integrations (3rd-party forms -> webhook)
    enable_external_forms = db.Column(db.Boolean, nullable=False, default=False)
    # Allow admins to enable/disable rolling quotes shown in the UI
    rolling_quotes_enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @classmethod
    def get(cls):
        from sqlalchemy import text

        # First do a minimal raw query that only touches the table existence
        # and primary key so we avoid referencing model columns that may be
        # missing in an out-of-date production schema. If this fails, fall
        # back to returning an in-memory default to keep admin pages working.
        try:
            row = db.session.execute(text("SELECT id FROM feature_flags LIMIT 1")).fetchone()
        except Exception:
            try:
                from flask import current_app

                current_app.logger.exception("FeatureFlags: quick probe failed")
            except Exception:
                pass
            try:
                db.session.rollback()
            except Exception:
                pass
            return cls()

        # If table exists but probe returned no rows, return or create a row.
        if not row:
            try:
                # Try to create a new DB-backed row; if this fails due to schema
                # issues, fall back to an in-memory default.
                f = cls()
                db.session.add(f)
                db.session.commit()
                return f
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                return cls()

        # If an id exists, attempt to load the ORM object but tolerate failures.
        try:
            # row[0] is the id
            f = db.session.get(cls, row[0])
            if f:
                return f
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            return cls()
        return cls()


class RejectRequestConfig(TenantScopedMixin, db.Model):
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
        try:
            cfg = cls.query.first()
        except Exception:
            try:
                db.session.rollback()
                cfg = cls.query.first()
            except Exception:
                cfg = None
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


class StatusBucket(TenantScopedMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    department_name = db.Column(db.String(10), nullable=True)
    order = db.Column(db.Integer, nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Optional workflow assigned to this bucket (scoped by department or global)
    workflow_id = db.Column(db.Integer, db.ForeignKey("workflow.id"), nullable=True)
    workflow = db.relationship("Workflow", backref="buckets")
    statuses = db.relationship(
        "BucketStatus", backref="bucket", lazy="dynamic", cascade="all, delete-orphan"
    )


class BucketStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bucket_id = db.Column(db.Integer, db.ForeignKey("status_bucket.id"), nullable=False)
    status_code = db.Column(db.String(80), nullable=False)
    order = db.Column(db.Integer, nullable=False, default=0)


class AuditLog(TenantScopedMixin, db.Model):
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


class SiteConfig(TenantScopedMixin, db.Model):
    """Singleton site configuration for banner and rolling quotes."""

    id = db.Column(db.Integer, primary_key=True)
    brand_name = db.Column(db.String(120), nullable=True)
    logo_filename = db.Column(db.String(255), nullable=True)
    theme_preset = db.Column(db.String(40), nullable=False, default="default")
    navbar_banner = db.Column(db.String(500), nullable=True)
    show_banner = db.Column(db.Boolean, nullable=False, default=False)
    _rolling_quotes = db.Column(
        "rolling_quotes", db.Text, nullable=True
    )  # JSON list of strings
    _rolling_quotes = db.Column(
        "rolling_quotes", db.Text, nullable=True
    )  # JSON list of strings (legacy single unnamed list)
    _rolling_quote_sets = db.Column(
        "rolling_quote_sets", db.Text, nullable=True
    )  # JSON map of named sets -> list of strings
    active_quote_set = db.Column(db.String(80), nullable=True, default="default")
    quote_permissions = db.Column(db.Text, nullable=True)  # JSON: {"departments":{code:[sets]},"users":{email:[sets]}}
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Default quote sets shipped with the app. Admin may override via SiteConfig.
    DEFAULT_QUOTE_SETS = {
        "default": [
            "Sort today: socks first, worries later.",
            "A folded stack is a small victory.",
            "One load at a time, one win at a time.",
            "Fresh socks, fresh perspective.",
            "Turn laundry into a tiny ritual of calm.",
        ],
        # two new themes requested by the user, each matching the default count
        "sales": [
            "Sell the problem you solve, not the product.",
            "Follow up once is good; follow up twice closes deals.",
            "People buy solutions, not features.",
            "Ask more questions; you sell fewer assumptions.",
            "Pitch benefits over features and watch interest grow.",
        ],
        "motivational": [
            "Progress, not perfection.",
            "Small habits compound into big results.",
            "Show up today; momentum finds you tomorrow.",
            "Focus on the next right step.",
            "Your only limit is the one you set yourself.",
        ],
        # rename riddles to be explicitly laundry-themed and add a fifth
        "laundry riddles": [
            "I speak without a mouth and hear without ears. What am I? (An echo)",
            "I have keys but no locks. What am I? (A piano)",
            "What has hands but cannot clap? (A clock)",
            "The more you take, the more you leave behind. What are they? (Footsteps)",
            "What gets wetter the more it dries? (A towel)",
        ],
        # an engineering-focused set requested for motivation
        "engineering": [
            "First, solve the problem. Then, write the code.",
            "Experience is the name everyone gives to their mistakes.",
            "If it works, it’s obsolete. If it doesn’t work, it’s creative.",
            "Optimism is an occupational hazard of programming; feedback is the cure.",
            "In engineering, absence of evidence is not evidence of absence.",
        ],
        "productivity": [
            "Eat the frog first and the rest of the day is easy.",
            "You can do anything, but not everything.",
            "Progress, not perfection.",
            "A to-do list is good; a done list is better.",
            "Do the hard work now so it’s easy tomorrow.",
        ],
        "leadership": [
            "Leaders eat last.",
            "Manage the system, not the people.",
            "Don’t ask others to do what you wouldn’t do yourself.",
            "Earn trust before asking for effort.",
            "Leadership is influence, not title.",
        ],
        "innovation": [
            "Fail fast, learn faster.",
            "Question assumptions; they’re free to discard.",
            "If it hasn’t been done, it may not be worth doing—or you may be the first.",
            "Disrupt yourself before someone else does.",
            "Creativity is intelligence having fun.",
        ],
        "customer-centric": [
            "Start with the customer and work backwards.",
            "Delight > satisfy.",
            "Listen twice as much as you speak.",
            "Solve problems they didn’t know they had.",
            "Know your user better than they know themselves.",
        ],
        "coffee-humour": [
            "Code runs faster after coffee.",
            "Decaf is for the weak.",
            "Instant human, just add coffee.",
            "Behind every successful developer is a substantial amount of coffee.",
            "Coffee: because adulting is hard.",
        ],
        "wellbeing": [
            "Take a walk; the code will still be there.",
            "Rest is not a reward; it’s a requirement.",
            "You are not a machine; mind the breaks.",
            "Healthy body, healthy debugging.",
            "Step away from the screen; your eyes will thank you.",
        ],
    }

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
        # Prefer named quote sets when available and return the active set.
        try:
            sets = {}
            if self._rolling_quote_sets:
                parsed = json.loads(self._rolling_quote_sets)
                if isinstance(parsed, dict):
                    for k, v in parsed.items():
                        if isinstance(v, list):
                            sets[str(k)] = [str(x).strip() for x in v if str(x).strip()]
            # Legacy single list -> populate default set
            if not sets and self._rolling_quotes:
                try:
                    parsed = json.loads(self._rolling_quotes)
                    if isinstance(parsed, list):
                        sets["default"] = [str(x).strip() for x in parsed if str(x).strip()]
                except Exception:
                    sets["default"] = [
                        line.strip()
                        for line in str(self._rolling_quotes).splitlines()
                        if line.strip()
                    ]
            if not sets:
                sets = type(self).DEFAULT_QUOTE_SETS.copy()

            active = (self.active_quote_set or "default")
            if active in sets:
                return sets.get(active, [])
            # fallback to the first available set
            return next(iter(sets.values()))
        except Exception:
            # very defensive fallback to original single-string behaviour
            if not self._rolling_quotes:
                return []
            try:
                parsed = json.loads(self._rolling_quotes)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                return [
                    line.strip()
                    for line in str(self._rolling_quotes).splitlines()
                    if line.strip()
                ]

    @property
    def rolling_quote_sets(self):
        """Return a dict of named quote-sets; never returns empty dict (falls back to defaults)."""
        try:
            if self._rolling_quote_sets:
                parsed = json.loads(self._rolling_quote_sets)
                if isinstance(parsed, dict):
                    out = {}
                    for k, v in parsed.items():
                        if isinstance(v, list):
                            out[str(k)] = [str(x).strip() for x in v if str(x).strip()]
                    if out:
                        return out
        except Exception:
            pass
        # fallback: if legacy single list exists, expose it as "default"
        try:
            if self._rolling_quotes:
                parsed = json.loads(self._rolling_quotes)
                if isinstance(parsed, list):
                    return {"default": [str(x).strip() for x in parsed if str(x).strip()]}
        except Exception:
            if self._rolling_quotes:
                return {"default": [
                    line.strip() for line in str(self._rolling_quotes).splitlines() if line.strip()
                ]}
        return type(self).DEFAULT_QUOTE_SETS.copy()

    @property
    def parsed_quote_permissions(self):
        """Return normalized quote permissions for departments and users."""
        empty = {"departments": {}, "users": {}}
        if not self.quote_permissions:
            return empty
        try:
            parsed = json.loads(self.quote_permissions)
        except Exception:
            return empty
        if not isinstance(parsed, dict):
            return empty

        def _normalize(mapping):
            if not isinstance(mapping, dict):
                return {}
            normalized = {}
            for key, values in mapping.items():
                name = str(key or "").strip()
                if not name:
                    continue
                if isinstance(values, list):
                    cleaned = [str(v).strip() for v in values if str(v).strip()]
                elif isinstance(values, str):
                    cleaned = [str(v).strip() for v in values.split(",") if str(v).strip()]
                else:
                    cleaned = []
                normalized[name] = cleaned
            return normalized

        return {
            "departments": _normalize(parsed.get("departments")),
            "users": _normalize(parsed.get("users")),
        }

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
        try:
            cfg = cls.query.first()
        except Exception:
            try:
                db.session.rollback()
                cfg = cls.query.first()
            except Exception:
                cfg = None
        if not cfg:
            cfg = cls()
            db.session.add(cfg)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        return cfg


class Department(TenantScopedMixin, db.Model):
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


class StatusOption(TenantScopedMixin, db.Model):
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
    # When True, selecting this status requires executive approval
    executive_approval_required = db.Column(db.Boolean, nullable=False, default=False)
    # When True, selecting this status requires specifying a sales list number
    sales_list_number_required = db.Column(db.Boolean, nullable=False, default=False)
    # When True, notifications for this status should be delivered only to
    # the originator (the user who created the request) rather than the
    # entire owner department. Admin toggle exposed in the UI.
    notify_to_originator_only = db.Column(db.Boolean, nullable=False, default=False)


class Workflow(TenantScopedMixin, db.Model):
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
    # When True, this workflow has been saved as a draft and awaits an
    # explicit "implement" step to create status options or apply changes.
    implementation_pending = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class DepartmentEditor(TenantScopedMixin, db.Model):
    """Per-department edit privileges assigned to users by admins."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", backref="dept_editor_roles")
    department = db.Column(db.String(2), nullable=False, index=True)
    can_edit = db.Column(db.Boolean, nullable=False, default=True)
    can_view_metrics = db.Column(db.Boolean, nullable=False, default=False)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint("user_id", "department", name="uq_user_dept_editor"),
    )


class UserDepartment(TenantScopedMixin, db.Model):
    """Additional department assignments for users.

    This table allows an admin to assign a user to multiple departments
    without changing their primary `User.department` value. The application
    will treat the primary `User.department` as the default and include any
    `UserDepartment` rows when presenting department-switch choices to the
    user.
    """

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", backref="departments")
    department = db.Column(db.String(2), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint("user_id", "department", name="uq_user_department"),
    )


class IntegrationConfig(TenantScopedMixin, db.Model):
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
    __table_args__ = (db.UniqueConstraint("department", "kind", name="uq_dept_kind"),)


class NotificationRetention(TenantScopedMixin, db.Model):
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
    clear_after_read_seconds = db.Column(
        db.Integer, nullable=True
    )  # seconds, nullable if using retain_until_eod
    max_notifications_per_user = db.Column(db.Integer, nullable=False, default=20)
    max_retention_days = db.Column(db.Integer, nullable=False, default=7)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @classmethod
    def get(cls):
        try:
            cfg = cls.query.first()
        except Exception:
            try:
                db.session.rollback()
                cfg = cls.query.first()
            except Exception:
                cfg = None
        if not cfg:
            cfg = cls()
            db.session.add(cfg)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        return cfg


class EmailRouting(TenantScopedMixin, db.Model):
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
            return cls.query.filter(
                db.func.lower(cls.recipient_email).like(like_val)
            ).all()
        except Exception:
            try:
                return cls.query.filter_by(
                    recipient_email=recipient.strip().lower()
                ).all()
            except Exception:
                return []
