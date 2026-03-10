"""Data models for users, requests, artifacts, comments, submissions, and audit trails."""

from datetime import datetime, timedelta
import json
import re
import secrets
from flask_login import UserMixin
from sqlalchemy.orm import validates
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
PRIORITIES = ("low", "medium", "high", "highest")  # highest is a special escalation tier above high

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
    "approval_decision",
)


TENANT_ROLES = (
    "platform_admin",
    "tenant_admin",
    "analyst",
    "member",
    "viewer",
)

GUEST_FORM_ACCESS_POLICIES = (
    ("public", "Anyone with the form link"),
    ("sso_linked", "Any SSO-linked account"),
    ("approved_sso_domains", "Approved SSO organizations only"),
    ("unaffiliated_only", "Unaffiliated accounts only"),
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
    provider_key = db.Column(db.String(80), nullable=True, index=True)
    correlation_id = db.Column(db.String(120), nullable=True, index=True)
    status = db.Column(db.String(30), nullable=False, default="pending", index=True)
    payload_json = db.Column(db.JSON, nullable=True)
    metadata_json = db.Column(db.JSON, nullable=True)
    last_error = db.Column(db.Text, nullable=True)
    retry_count = db.Column(db.Integer, nullable=False, default=0)
    last_attempt_at = db.Column(db.DateTime, nullable=True)
    next_retry_at = db.Column(db.DateTime, nullable=True, index=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class User(TenantScopedMixin, db.Model, UserMixin):
    """Application user account (local or SSO-backed)."""

    @property
    def department_obj(self):
        """Return the Department record for this user's primary department.

        This is a convenience used by notification rendering when templates are
        defined on departments. Returns ``None`` if no matching department can
        be found.
        """
        from .models import Department

        code = (getattr(self, "department", None) or "").strip().upper()
        if not code:
            return None
        return Department.query.filter_by(code=code).first()

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
    backup_approver_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    backup_approver = db.relationship(
        "User",
        foreign_keys=[backup_approver_user_id],
        remote_side=[id],
        backref="coverage_for_users",
        uselist=False,
    )
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
    # new user preference: show or hide the navbar vibe button
    vibe_button_enabled = db.Column(db.Boolean, nullable=False, default=True)
    # user preference: interval (in seconds) between quote rotations; allowed
    # values are multiples of 5 between 15 and 60.  We store as integer seconds
    # so the frontend can easily multiply by 1000.  When absent the default is
    # 15 seconds (the shortest allowable interval).
    quote_interval = db.Column(db.Integer, nullable=True, default=None)
    # user preference: whether first-use guidance panels should appear on
    # dashboard and admin landing surfaces.
    onboarding_guidance_enabled = db.Column(db.Boolean, nullable=False, default=True)

    # admin-configurable allowance of manual nudges the user may initiate per
    # UTC day. Defaults to 1 and capped at 5. Used by the `/push_nudge` route
    # to throttle excessive reminders.
    daily_nudge_limit = db.Column(db.Integer, nullable=False, default=1)

    @validates("daily_nudge_limit")
    def _validate_daily_nudge_limit(self, key, value):
        if value is None or value == "":
            return 1
        try:
            iv = int(value)
        except Exception:
            raise ValueError("daily_nudge_limit must be an integer")
        if iv < 1 or iv > 5:
            raise ValueError("daily_nudge_limit must be between 1 and 5")
        return iv

    # Ensure we always store a normalized (lowercase, stripped) key for the
    # quote set.  This protects against manual database edits or historical
    # values that differed in case which could otherwise be ignored by the
    # lookup logic in the layout context processor.
    @validates("quote_set")
    def _normalize_quote_set(self, key, value):
        if value is None:
            return None
        return str(value).strip().lower()

    @validates("quote_interval")
    def _validate_quote_interval(self, key, value):
        if value is None or value == "":
            return None
        try:
            iv = int(value)
        except Exception:
            raise ValueError("Quote interval must be an integer number of seconds")
        # permissible values are 15,20,...,60
        if iv < 15 or iv > 60 or iv % 5 != 0:
            raise ValueError("Quote interval must be between 15 and 60 seconds in 5‑second steps")
        return iv
    # Persist the last department the user was viewing when they logged out
    # or switched contexts. This is used to restore their active department
    # on subsequent logins when they have multiple department assignments.
    last_active_dept = db.Column(db.String(2), nullable=True)
    # admin-managed landing preference so people can drop into the most useful
    # workspace immediately after login.
    preferred_start_page = db.Column(db.String(40), nullable=True, default="dashboard")
    preferred_start_department = db.Column(db.String(2), nullable=True)
    # admin-managed list of departments the user wants surfaced as quick-access
    # queue links on the dashboard. Stored as JSON text for compatibility with
    # existing SQLite and Postgres deployments.
    watched_departments_json = db.Column(db.Text, nullable=True)
    # admin-managed extra departments whose notifications should also be routed
    # to this user even if they are not the primary owner of that queue.
    notification_departments_json = db.Column(db.Text, nullable=True)
    # lightweight role preset used by admin bulk actions and user editing. The
    # preset is translated into DepartmentEditor rows so existing permission
    # checks keep working without bespoke branching throughout the app.
    workflow_role_profile = db.Column(db.String(40), nullable=True, default="member")

    WORKFLOW_ROLE_PROFILES = {
        "member": {
            "label": "Member",
            "can_edit": False,
            "can_view_metrics": False,
            "can_change_priority": False,
        },
        "coordinator": {
            "label": "Coordinator",
            "can_edit": True,
            "can_view_metrics": False,
            "can_change_priority": False,
        },
        "metrics_lead": {
            "label": "Metrics Lead",
            "can_edit": True,
            "can_view_metrics": True,
            "can_change_priority": False,
        },
        "queue_lead": {
            "label": "Queue Lead",
            "can_edit": True,
            "can_view_metrics": True,
            "can_change_priority": True,
        },
    }

    @validates("preferred_start_page")
    def _normalize_preferred_start_page(self, key, value):
        normalized = str(value or "dashboard").strip().lower() or "dashboard"
        allowed = {"dashboard", "search", "metrics", "admin_monitor"}
        return normalized if normalized in allowed else "dashboard"

    @validates("preferred_start_department")
    def _normalize_preferred_start_department(self, key, value):
        if value is None:
            return None
        normalized = str(value).strip().upper()
        return normalized or None

    @validates("workflow_role_profile")
    def _normalize_workflow_role_profile(self, key, value):
        normalized = str(value or "member").strip().lower() or "member"
        return normalized if normalized in self.WORKFLOW_ROLE_PROFILES else "member"

    @property
    def watched_departments(self) -> list[str]:
        try:
            parsed = json.loads(self.watched_departments_json or "[]")
        except Exception:
            parsed = []
        if not isinstance(parsed, list):
            return []
        cleaned = []
        for item in parsed:
            dept = str(item or "").strip().upper()
            if dept and dept not in cleaned:
                cleaned.append(dept)
        return cleaned

    @watched_departments.setter
    def watched_departments(self, value):
        cleaned = []
        for item in value or []:
            dept = str(item or "").strip().upper()
            if dept and dept not in cleaned:
                cleaned.append(dept)
        self.watched_departments_json = json.dumps(cleaned)

    @property
    def notification_departments(self) -> list[str]:
        try:
            parsed = json.loads(self.notification_departments_json or "[]")
        except Exception:
            parsed = []
        if not isinstance(parsed, list):
            return []
        cleaned = []
        for item in parsed:
            dept = str(item or "").strip().upper()
            if dept and dept not in cleaned:
                cleaned.append(dept)
        return cleaned

    @notification_departments.setter
    def notification_departments(self, value):
        cleaned = []
        for item in value or []:
            dept = str(item or "").strip().upper()
            if dept and dept not in cleaned:
                cleaned.append(dept)
        self.notification_departments_json = json.dumps(cleaned)

    @property
    def workflow_role_profile_label(self) -> str:
        profile = self.WORKFLOW_ROLE_PROFILES.get(
            str(getattr(self, "workflow_role_profile", "member") or "member").strip().lower(),
            self.WORKFLOW_ROLE_PROFILES["member"],
        )
        return profile.get("label", "Member")


class SavedSearchView(TenantScopedMixin, db.Model):
    """User-saved search filters that double as lightweight personal dashboard shortcuts."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    user = db.relationship("User", backref="saved_search_views")
    name = db.Column(db.String(120), nullable=False)
    endpoint = db.Column(db.String(120), nullable=False, default="requests.search_requests")
    query_json = db.Column(db.Text, nullable=True)
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("user_id", "name", name="uq_saved_search_view_user_name"),
    )

    @property
    def params(self) -> dict:
        try:
            parsed = json.loads(self.query_json or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    @params.setter
    def params(self, value):
        cleaned = value if isinstance(value, dict) else {}
        self.query_json = json.dumps(cleaned)


class Notification(TenantScopedMixin, db.Model):
    """In-app notification with optional deep link and dedupe key."""

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", foreign_keys=[user_id], backref="notifications")

    # optional actor/initiator of the notification (e.g. which user pushed a
    # reminder); this allows enforcing per-user rate limits on nudges. It is
    # deliberately nullable so that existing rows are unaffected and other
    # notification types need not populate it.
    actor_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    actor_user = db.relationship(
        "User", foreign_keys=[actor_user_id], backref="initiated_notifications"
    )

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
    approval_steps = db.relationship(
        "RequestApproval", backref="request", lazy=True, cascade="all, delete-orphan"
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


# layout options for form templates, similar to guest forms.  This allows
# an external service or client to request the visual arrangement when
# generating their own copy of the form for submission.
FORM_TEMPLATE_LAYOUT_CHOICES = [
    ("standard", "Standard"),
    ("compact", "Compact"),
    ("spacious", "Spacious"),
]


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

    @property
    def layout_label(self):
        mapping = dict(FORM_TEMPLATE_LAYOUT_CHOICES)
        return mapping.get(self.layout, mapping.get("standard"))
    # layout of the template for externally generated forms; used by third
    # party clients to mirror the same spacing/width choices that the app
    # would render.  Defaults to 'standard'.
    layout = db.Column(db.String(20), nullable=False, default="standard")


# layout options that determine the visual presentation of the public
# guest intake form.  Admins can choose one of these when they create/edit
# a guest form and the frontend will apply a corresponding CSS class.
GUEST_FORM_LAYOUT_CHOICES = [
    ("standard", "Standard"),
    ("compact", "Compact"),
    ("spacious", "Spacious"),
]


class GuestForm(TenantScopedMixin, db.Model):
    """Admin-manageable guest form instance used for public/guest submissions.

    Allows per-form toggles such as requiring an SSO-linked account to submit.
    More advanced access policies can target approved SSO organizations by
    email domain or reserve a form for unaffiliated submitters.

    A new ``layout`` column holds a simple identifier that drives the HTML/CSS
    class applied to the external intake page so that different forms can have
    distinct visual arrangements (for example, a more compact or spacious
    layout).
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), nullable=False, unique=True, index=True)
    template_id = db.Column(db.Integer, db.ForeignKey("form_template.id"), nullable=True)
    template = db.relationship("FormTemplate", backref="guest_forms")
    require_sso = db.Column(db.Boolean, nullable=False, default=False)
    access_policy = db.Column(db.String(40), nullable=True, default="public")
    allowed_email_domains = db.Column(db.Text, nullable=True)
    credential_requirements_json = db.Column(db.Text, nullable=True)
    owner_department = db.Column(db.String(2), nullable=False, default="B")
    layout = db.Column(db.String(20), nullable=False, default="standard")
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @classmethod
    def access_policy_choices(cls):
        return list(GUEST_FORM_ACCESS_POLICIES)

    @property
    def normalized_access_policy(self):
        valid = {choice[0] for choice in GUEST_FORM_ACCESS_POLICIES}
        raw = (self.access_policy or "").strip().lower()
        if raw in valid:
            return raw
        return "sso_linked" if bool(self.require_sso) else "public"

    @property
    def access_policy_label(self):
        mapping = dict(GUEST_FORM_ACCESS_POLICIES)
        return mapping.get(self.normalized_access_policy, mapping["public"])

    @property
    def access_policy_hint(self):
        hints = {
            "public": "Anyone with the link can submit this form.",
            "sso_linked": "Submitters must already be linked to an SSO-backed user account.",
            "approved_sso_domains": "Submitters must be SSO-linked and their email domain must match an approved organization.",
            "unaffiliated_only": "This form is reserved for non-SSO submitters outside the approved organization list.",
        }
        return hints.get(self.normalized_access_policy, hints["public"])

    @property
    def allowed_email_domain_list(self):
        raw = self.allowed_email_domains or ""
        items = []
        for part in str(raw).replace("\n", ",").split(","):
            domain = str(part or "").strip().lower().lstrip("@")
            if domain and domain not in items:
                items.append(domain)
        return items

    @property
    def layout_label(self):
        mapping = dict(GUEST_FORM_LAYOUT_CHOICES)
        return mapping.get(self.layout, mapping.get("standard"))

    @property
    def credential_requirements(self):
        raw = (self.credential_requirements_json or "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @credential_requirements.setter
    def credential_requirements(self, value):
        if not value:
            self.credential_requirements_json = None
            return
        if isinstance(value, str):
            raw = value.strip()
            self.credential_requirements_json = raw or None
            return
        self.credential_requirements_json = json.dumps(value)

    @property
    def credential_requirements_pretty_json(self):
        data = self.credential_requirements
        if not data:
            return ""
        try:
            return json.dumps(data, indent=2, sort_keys=True)
        except Exception:
            return self.credential_requirements_json or ""

    def evaluate_submitter_access(self, email: str, user=None):
        email_n = (email or "").strip().lower()
        domain = email_n.split("@", 1)[1] if "@" in email_n else ""
        policy = self.normalized_access_policy
        approved_domains = set(self.allowed_email_domain_list)
        has_sso = bool(user and getattr(user, "sso_sub", None))
        in_approved_domain = bool(domain and domain in approved_domains)

        allowed = True
        message = ""

        if policy == "sso_linked":
            allowed = has_sso
            if not allowed:
                message = "This form requires an SSO-linked account."
        elif policy == "approved_sso_domains":
            allowed = has_sso and in_approved_domain
            if not allowed:
                if not has_sso:
                    message = "This form requires an SSO-linked account from an approved organization."
                else:
                    message = "This form is limited to approved SSO organizations."
        elif policy == "unaffiliated_only":
            allowed = (not has_sso) and (not approved_domains or not in_approved_domain)
            if not allowed:
                message = "This form is reserved for unaffiliated submitters."

        return {
            "allowed": allowed,
            "policy": policy,
            "message": message,
            "email_domain": domain,
            "has_sso": has_sso,
            "approved_domain": in_approved_domain,
            "credential_requirements": self.credential_requirements,
        }


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
    section_name = db.Column(db.String(200), nullable=True)
    hint = db.Column(db.String(300), nullable=True)
    verification = db.Column(db.JSON, nullable=True)
    requirement_rules = db.Column(db.JSON, nullable=True)
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


class TemplateSwapRule(TenantScopedMixin, db.Model):
    """Map a trigger (field name + value) on a source template to a target template.

    This allows the frontend to ask the app whether selecting a particular
    option should swap the active template mid-form and optionally update
    routing (owner department) for the submission.
    """

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("form_template.id"), nullable=False)
    # the field name in the current template that triggers the swap
    trigger_field_name = db.Column(db.String(200), nullable=False)
    # the exact field value that triggers the swap
    trigger_value = db.Column(db.String(400), nullable=False)
    # target template to switch to
    target_template_id = db.Column(db.Integer, db.ForeignKey("form_template.id"), nullable=False)
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
    ocr_text = db.Column(db.Text, nullable=True)

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
    guest_dashboard_enabled = db.Column(db.Boolean, nullable=False, default=True)
    guest_submission_enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    DEFAULTS = {
        "enable_notifications": True,
        "enable_nudges": True,
        "allow_user_nudges": False,
        "vibe_enabled": True,
        "sso_admin_sync_enabled": True,
        "sso_department_sync_enabled": False,
        "enable_external_forms": False,
        "rolling_quotes_enabled": True,
        "guest_dashboard_enabled": True,
        "guest_submission_enabled": True,
    }

    @classmethod
    def default_instance(cls):
        flags = cls()
        for attr, default in cls.DEFAULTS.items():
            setattr(flags, attr, default)
        return flags

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
            return cls.default_instance()

        # If table exists but probe returned no rows, return or create a row.
        if not row:
            try:
                # Try to create a new DB-backed row; if this fails due to schema
                # issues, fall back to an in-memory default.
                f = cls.default_instance()
                db.session.add(f)
                db.session.commit()
                return f
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                return cls.default_instance()

        # If an id exists, attempt to load the ORM object but tolerate failures.
        try:
            # row[0] is the id
            f = db.session.get(cls, row[0])
            if f:
                # ensure no None values linger; treat them as defaults
                for attr, default in cls.DEFAULTS.items():
                    if getattr(f, attr, None) is None:
                        try:
                            setattr(f, attr, default)
                        except Exception:
                            pass
                return f
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            return cls.default_instance()
        return cls.default_instance()


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


class RequestApproval(TenantScopedMixin, db.Model):
    """A single approval-stage record created when a request enters an approval status."""

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("request.id"), nullable=False, index=True)
    status_code = db.Column(db.String(80), nullable=False, index=True)
    cycle_index = db.Column(db.Integer, nullable=False, default=1)
    stage_order = db.Column(db.Integer, nullable=False, default=0)
    stage_name = db.Column(db.String(200), nullable=False)
    required_role = db.Column(db.String(40), nullable=True)
    required_department = db.Column(db.String(10), nullable=True)
    state = db.Column(db.String(30), nullable=False, default="pending", index=True)
    decided_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    decided_by_user = db.relationship("User", foreign_keys=[decided_by_user_id])
    decision_note = db.Column(db.Text, nullable=True)
    decided_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    @property
    def is_complete(self) -> bool:
        return self.state in {"approved", "changes_requested"}


class SiteConfig(TenantScopedMixin, db.Model):
    """Singleton site configuration for banner and rolling quotes."""

    id = db.Column(db.Integer, primary_key=True)
    brand_name = db.Column(db.String(120), nullable=True)
    logo_filename = db.Column(db.String(255), nullable=True)
    theme_preset = db.Column(db.String(40), nullable=False, default="default")
    # optional external link used by branding; when set we surface an absolute
    # href on the navbar logo that points off-site.  Stored as a full URL so we
    # can open it in a new tab without forcing users through our own routing.
    company_url = db.Column(db.String(255), nullable=True)
    navbar_banner = db.Column(db.String(500), nullable=True)
    show_banner = db.Column(db.Boolean, nullable=False, default=False)
    _rolling_quotes = db.Column(
        "rolling_quotes", db.Text, nullable=True
    )  # JSON list of strings (legacy single unnamed list)
    _rolling_quote_sets = db.Column(
        "rolling_quote_sets", db.Text, nullable=True
    )  # JSON map of named sets -> list of strings
    active_quote_set = db.Column(db.String(80), nullable=True, default="motivational")
    quote_permissions = db.Column(db.Text, nullable=True)  # JSON: {"departments":{code:[sets]},"users":{email:[sets]}}
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    MAX_QUOTE_LENGTH = 160

    # Default quote sets shipped with the app. Admin may override via SiteConfig.
    # Each set is required to contain exactly 30 entries; when the app defines
    # fewer than that we pad with benign placeholder lines to meet the target.
    _QUOTE_SETS_BASE = {
        "default": [
            "Start where you are and make this hour count.",
            "A calm plan beats rushed chaos every time.",
            "One finished task can reset an entire day.",
            "Consistency is quieter than hype and stronger than both.",
            "Keep moving; clarity usually catches up to action.",
            "A steady pace still reaches meaningful places.",
            "Momentum grows when you honor the next small promise.",
            "Give today's work your full attention, not your full panic.",
        ],
        "sales": [
            "Lead with the customer's problem and trust the value to follow.",
            "The best follow-up sounds helpful, not desperate.",
            "Curiosity closes more deals than pressure ever will.",
            "When you listen well, the next right pitch gets easier.",
            "Confidence lands best when it is backed by preparation.",
            "One thoughtful conversation can change the whole quarter.",
            "Sell with clarity, and decisions feel lighter for everyone.",
            "Progress in sales often starts with one more honest question.",
        ],
        "motivational": [
            "Progress, not perfection.",
            "Small habits compound into big results.",
            "Show up today; momentum finds you tomorrow.",
            "Focus on the next right step.",
            "Discipline is a form of self-respect.",
            "You do not need a new day to make a better choice.",
            "Quiet effort still changes loud outcomes.",
            "Keep your promises to yourself, especially the small ones.",
            "Courage often looks like doing the ordinary thing again.",
            "A little progress with intention beats a lot of delay.",
            "Your pace is allowed to be steady and still be powerful.",
            "Make the day answer to your priorities, not your mood.",
        ],
        # Keep the legacy key for compatibility while making the content
        # feel like playful laundry motivation instead of unrelated riddles.
        "laundry riddles": [
            "Turn laundry into a tiny ritual of calm.",
            "A folded stack is proof that order can be built.",
            "One load at a time is still a real kind of progress.",
            "Fresh clothes can reset more than a closet.",
            "Match the socks, clear the mind.",
            "Wash, dry, fold, done: momentum loves a simple rhythm.",
            "Clean routines make crowded weeks feel lighter.",
            "Finishing the basket feels better than avoiding it ever did.",
        ],
        "chores": [
            "A five-minute tidy can rescue an entire evening.",
            "The sink looks less dramatic after the first plate.",
            "Small chores are easier when you stop negotiating with them.",
            "A reset room can reset a restless mind.",
            "Wipe the counter, lighten the mood.",
            "Done is a beautiful look for the to-do list at home.",
            "Routine care keeps tomorrow from feeling crowded.",
            "A little maintenance is a quiet form of kindness to yourself.",
        ],
        "engineering": [
            "First, solve the problem. Then, write the code.",
            "Readable wins twice: once today and again during the next fix.",
            "A small reliable improvement beats a dramatic fragile rewrite.",
            "Good systems are built by patient iterations, not lucky guesses.",
            "Debugging is proof that you are getting closer to understanding.",
            "Strong foundations make fast shipping safer.",
            "Clarity in the design saves courage in production.",
            "The next clean commit is still forward motion.",
        ],
        "productivity": [
            "Protect the first hour and the rest of the day improves.",
            "A shorter list with real priorities is still ambitious.",
            "Do the hardest useful thing before the noise gets loud.",
            "Progress improves when attention stops multitasking.",
            "The right system makes discipline easier to repeat.",
            "Completion creates energy that planning alone never will.",
            "Your calendar should reflect your goals, not your guilt.",
            "Finish one meaningful task and let momentum do the rest.",
        ],
        "leadership": [
            "Calm leadership gives everyone else room to think.",
            "The clearest standard is the one you model yourself.",
            "Trust grows when your actions arrive before your slogans.",
            "Good leaders make the work feel possible, not smaller.",
            "Consistency builds credibility long before titles do.",
            "The strongest teams are shaped by steady clarity.",
            "People commit faster when they feel respected.",
            "Leadership is often the art of reducing confusion.",
        ],
        "innovation": [
            "Better questions usually arrive before better products.",
            "Try the bold idea, then make it workable.",
            "Original thinking gets stronger when it meets real constraints.",
            "Test early enough that learning still feels cheap.",
            "Curiosity is a competitive advantage when it becomes action.",
            "Useful innovation solves friction, not just boredom.",
            "Small experiments can uncover very large opportunities.",
            "New value often starts as an awkward first version.",
        ],
        "customer-centric": [
            "Listen closely enough and the roadmap starts writing itself.",
            "The customer usually remembers how easy you made things feel.",
            "Useful service is one of the fastest ways to build trust.",
            "Solve the real pain point and the rest gets simpler.",
            "Empathy is a practical business skill.",
            "Clarity for the customer is a form of quality.",
            "Better experiences are built from better noticing.",
            "Make the next step obvious and confidence goes up.",
        ],
        "coffee-humour": [
            "Coffee cannot solve everything, but it can improve the opening draft.",
            "A warm mug and a clear task list make a strong alliance.",
            "Caffeine is not a strategy, but it is a respectable sidekick.",
            "Some breakthroughs begin one sip before they make sense.",
            "Coffee first, brilliance immediately after is the aspiration.",
            "A patient brew can rescue a noisy morning.",
            "Optimism tastes stronger after the first cup.",
            "Even the calendar looks friendlier beside good coffee.",
        ],
        "wellbeing": [
            "Rest is productive when it protects tomorrow's focus.",
            "A breath, a stretch, and a reset can change the tone of the day.",
            "You work better when you remember you are a person first.",
            "Steady energy matters more than dramatic bursts.",
            "Protecting your peace is part of doing good work.",
            "A short walk can untangle what force cannot.",
            "Recovery is not separate from performance; it supports it.",
            "Gentle routines often create the strongest resilience.",
        ],
    }

    _QUOTE_SET_PADDING = {
        "default": {
            "openings": ["Keep the day simple", "Choose the next useful step", "Stay steady", "Aim for calm progress"],
            "actions": ["finish one meaningful task", "honor the plan you made", "let small wins stack up", "give your attention a single job"],
            "payoffs": ["momentum will meet you", "clarity tends to follow", "the day will feel lighter", "confidence grows from repetition"],
        },
        "sales": {
            "openings": ["Lead with value", "Stay curious", "Follow up with purpose", "Keep the conversation human"],
            "actions": ["ask one better question", "solve the real hesitation", "make the next decision easy", "show the outcome, not just the feature list"],
            "payoffs": ["trust grows faster", "good deals get easier to spot", "clarity does the heavy lifting", "relationships outlast the quarter"],
        },
        "motivational": {
            "openings": ["Start anyway", "Stay with the process", "Protect your momentum", "Trust the small win"],
            "actions": ["do the next right thing", "repeat the habit that helps", "move before doubt gets louder", "keep your standards close"],
            "payoffs": ["results will eventually catch up", "your confidence will strengthen", "today will count", "progress will stop feeling accidental"],
        },
        "laundry riddles": {
            "openings": ["Sort the load", "Fold what is ready", "Reset the basket", "Treat laundry like a checkpoint"],
            "actions": ["finish one cycle at a time", "pair the socks before the excuses", "make the room feel cared for", "turn the routine into rhythm"],
            "payoffs": ["calm returns faster", "home feels easier to enter", "order becomes visible", "the week gets less noisy"],
        },
        "chores": {
            "openings": ["Tidy a little now", "Pick one corner", "Handle the simple task", "Reset the space"],
            "actions": ["clear one surface", "wash the next dish", "close one household loop", "do the part future-you will notice"],
            "payoffs": ["the room will breathe again", "stress loses some volume", "evening gets easier", "routine starts helping you back"],
        },
        "engineering": {
            "openings": ["Ship with intention", "Debug with patience", "Design for clarity", "Keep the system understandable"],
            "actions": ["reduce one source of risk", "write the simpler version first", "improve the path that fails most often", "name things so the code can explain itself"],
            "payoffs": ["future fixes get easier", "reliability compounds", "the next release feels safer", "the team moves faster together"],
        },
        "productivity": {
            "openings": ["Guard your focus", "Start with the priority", "Trim the noise", "Finish before you optimize"],
            "actions": ["protect one block of deep work", "close the task that matters most", "trade urgency for intention", "let the checklist support you"],
            "payoffs": ["time opens up", "progress gets measurable", "the backlog feels smaller", "energy stops leaking away"],
        },
        "leadership": {
            "openings": ["Lead calmly", "Model the standard", "Communicate early", "Make the path clearer"],
            "actions": ["remove one point of confusion", "match your actions to your message", "set the tone with consistency", "help the team see the priority"],
            "payoffs": ["trust has room to grow", "people move with confidence", "the team steadies faster", "clarity becomes contagious"],
        },
        "innovation": {
            "openings": ["Test the new idea", "Challenge the assumption", "Stay experimental", "Build the first useful version"],
            "actions": ["learn from the quick draft", "keep curiosity attached to execution", "treat feedback like fuel", "let constraints sharpen the concept"],
            "payoffs": ["the next version gets smarter", "new options appear", "useful change becomes possible", "creative work gains traction"],
        },
        "customer-centric": {
            "openings": ["Start with the customer", "Listen one layer deeper", "Reduce the friction", "Make the next step easy"],
            "actions": ["solve the felt pain point", "write for clarity", "keep empathy practical", "design around their real goal"],
            "payoffs": ["trust gets stronger", "adoption feels natural", "support gets lighter", "people remember the experience"],
        },
        "coffee-humour": {
            "openings": ["Respect the coffee", "Let the mug buy you a minute", "Begin after the first sip", "Pair the plan with caffeine"],
            "actions": ["tackle the task while the optimism is warm", "keep the humor in the process", "use the ritual to settle in", "start before the cup gets cold"],
            "payoffs": ["the morning feels friendlier", "the hard part looks smaller", "focus tends to show up", "the draft gets written"],
        },
        "wellbeing": {
            "openings": ["Protect your energy", "Choose a kinder pace", "Let recovery count", "Take the small pause"],
            "actions": ["breathe before the next push", "notice what your body is asking for", "rest before frustration hardens", "keep the routine sustainable"],
            "payoffs": ["resilience lasts longer", "focus returns cleaner", "stress loses its grip", "good work stays repeatable"],
        },
    }

    def _build_padded_quote_set(name, quotes, profiles=_QUOTE_SET_PADDING, max_length=MAX_QUOTE_LENGTH):
        cleaned = [
            str(item).strip()[:max_length]
            for item in (quotes or [])
            if str(item).strip()
        ][:30]
        if len(cleaned) >= 30:
            return cleaned

        profile = profiles.get(str(name or "").strip().lower()) or profiles["motivational"]
        seen = {item.casefold() for item in cleaned}

        for opening in profile.get("openings", []):
            for action in profile.get("actions", []):
                for payoff in profile.get("payoffs", []):
                    candidate = f"{opening}; {action}; {payoff}."
                    candidate = candidate[:max_length].strip()
                    key = candidate.casefold()
                    if candidate and key not in seen:
                        cleaned.append(candidate)
                        seen.add(key)
                    if len(cleaned) >= 30:
                        return cleaned[:30]

        theme = str(name or "motivation").replace("-", " ").strip() or "motivation"
        counter = 1
        while len(cleaned) < 30:
            candidate = (
                f"Keep {theme} moving with one clear step {counter}; "
                f"steady effort still counts."
            )[:max_length].strip()
            key = candidate.casefold()
            if key not in seen:
                cleaned.append(candidate)
                seen.add(key)
            counter += 1
        return cleaned[:30]

    DEFAULT_QUOTE_SETS = {}
    for name, quotes in _QUOTE_SETS_BASE.items():
        DEFAULT_QUOTE_SETS[name] = _build_padded_quote_set(name, quotes)

    @classmethod
    def normalize_quote_sets(cls, quote_sets=None):
        """Return quote sets with guaranteed quotes for each built-in set."""
        defaults = {
            str(name): cls._build_padded_quote_set(name, quotes)
            for name, quotes in cls._QUOTE_SETS_BASE.items()
        }

        normalized = {}
        if isinstance(quote_sets, dict):
            for raw_name, raw_quotes in quote_sets.items():
                name = str(raw_name or "").strip()
                if not name or not isinstance(raw_quotes, list):
                    continue
                cleaned = [
                    str(item).strip()[: cls.MAX_QUOTE_LENGTH]
                    for item in raw_quotes
                    if str(item).strip()
                ]
                if cleaned:
                    normalized[name] = cleaned

        merged = {}
        for name, quotes in defaults.items():
            merged[name] = list(normalized.get(name) or quotes)

        for name, quotes in normalized.items():
            if name not in merged:
                merged[name] = list(quotes)

        # enforce uniform 30-item length for every set using themed filler
        # language instead of generic placeholders.
        for name, quotes in merged.items():
            merged[name] = cls._build_padded_quote_set(name, quotes)
        return merged

    @classmethod
    def strip_generated_quote_padding(cls, name, quotes):
        pattern = re.compile(rf"^{re.escape(str(name))} quote \d+$", re.IGNORECASE)
        cleaned = []
        for quote in quotes or []:
            text = str(quote).strip()
            if not text:
                continue
            if pattern.fullmatch(text):
                continue
            cleaned.append(text)
        return cleaned

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
                    sets = type(self).normalize_quote_sets(parsed)
            # Legacy single list -> populate default set
            if not sets and self._rolling_quotes:
                try:
                    parsed = json.loads(self._rolling_quotes)
                    if isinstance(parsed, list):
                        sets = type(self).normalize_quote_sets({
                            "default": [str(x).strip() for x in parsed if str(x).strip()]
                        })
                except Exception:
                    sets = type(self).normalize_quote_sets({
                        "default": [
                            line.strip()
                            for line in str(self._rolling_quotes).splitlines()
                            if line.strip()
                        ]
                    })
            if not sets:
                sets = type(self).normalize_quote_sets()

            active = (self.active_quote_set or "motivational")
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
                    out = type(self).normalize_quote_sets(parsed)
                    if out:
                        return out
        except Exception:
            pass
        # fallback: if legacy single list exists, expose it as "default"
        try:
            if self._rolling_quotes:
                parsed = json.loads(self._rolling_quotes)
                if isinstance(parsed, list):
                    return type(self).normalize_quote_sets({
                        "default": [str(x).strip() for x in parsed if str(x).strip()]
                    })
        except Exception:
            if self._rolling_quotes:
                return type(self).normalize_quote_sets({
                    "default": [
                        line.strip() for line in str(self._rolling_quotes).splitlines() if line.strip()
                    ]
                })
        return type(self).normalize_quote_sets()

    @property
    def editable_quote_sets(self):
        """Return quote sets without auto-generated padding placeholders."""
        cleaned = {}
        for name, quotes in (self.rolling_quote_sets or {}).items():
            stripped = type(self).strip_generated_quote_padding(name, quotes)
            if stripped:
                cleaned[name] = stripped
        for name, quotes in type(self)._QUOTE_SETS_BASE.items():
            cleaned.setdefault(name, list(quotes))
        return cleaned

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

        def _normalize(mapping, *, lowercase_keys=False):
            if not isinstance(mapping, dict):
                return {}
            normalized = {}
            for key, values in mapping.items():
                name = str(key or "").strip()
                if not name:
                    continue
                if lowercase_keys:
                    name = name.lower()
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
            "users": _normalize(parsed.get("users"), lowercase_keys=True),
        }

    def allowed_quote_set_names_for_user(self, user=None):
        """Return visible quote-set names for a user in display order.

        Admins always receive the full configured list. For non-admin users,
        per-user permissions override department restrictions when present.
        """
        names = list((self.rolling_quote_sets or {}).keys())
        if not names:
            names = list(type(self).DEFAULT_QUOTE_SETS.keys())
        if not user or getattr(user, "is_admin", False):
            return names

        perms = self.parsed_quote_permissions
        email = str(getattr(user, "email", "") or "").strip().lower()
        dept = str(getattr(user, "department", "") or "").strip()

        user_allowed = perms.get("users", {}).get(email)
        dept_allowed = perms.get("departments", {}).get(dept)
        allowed = user_allowed if user_allowed is not None and len(user_allowed) > 0 else dept_allowed
        if not allowed:
            return names
        allowed_set = {str(name).strip() for name in allowed if str(name).strip()}
        filtered = [name for name in names if name in allowed_set]
        return filtered or names

    def resolve_quote_set_name_for_user(self, user=None):
        """Return the effective quote-set key a user should see."""
        names = self.allowed_quote_set_names_for_user(user)
        if not names:
            return None

        preferred = str(getattr(user, "quote_set", "") or "").strip().lower() if user else ""
        if preferred:
            for name in names:
                if str(name).lower() == preferred:
                    return name

        active = str(getattr(self, "active_quote_set", "") or "").strip().lower()
        if active:
            for name in names:
                if str(name).lower() == active:
                    return name

        for fallback in ("motivational", "default"):
            for name in names:
                if str(name).lower() == fallback:
                    return name

        return names[0]

    @rolling_quotes.setter
    def rolling_quotes(self, value):
        if value is None:
            self._rolling_quotes = None
            return
        if isinstance(value, list):
            cleaned = [str(x).strip()[: type(self).MAX_QUOTE_LENGTH] for x in value if str(x).strip()][:30]
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
                    cleaned = [
                        str(x).strip()[: type(self).MAX_QUOTE_LENGTH]
                        for x in parsed
                        if str(x).strip()
                    ][:30]
                    self._rolling_quotes = json.dumps(cleaned)
                    return
            except Exception:
                pass
            cleaned = [line.strip()[: type(self).MAX_QUOTE_LENGTH] for line in raw.splitlines() if line.strip()][:30]
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
        try:
            normalized_sets = cls.normalize_quote_sets(getattr(cfg, "rolling_quote_sets", None))
            current_sets = getattr(cfg, "rolling_quote_sets", None) or {}
            if normalized_sets != current_sets or not getattr(cfg, "_rolling_quote_sets", None):
                cfg._rolling_quote_sets = json.dumps(normalized_sets)
            active_quote_set = str(getattr(cfg, "active_quote_set", "") or "").strip().lower()
            if (
                not active_quote_set
                or active_quote_set not in normalized_sets
                or active_quote_set == "default"
            ):
                cfg.active_quote_set = "motivational" if "motivational" in normalized_sets else "default"
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
        return cfg


class Department(TenantScopedMixin, db.Model):
    """Optional persisted department metadata (code A/B/C and display label)."""

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(2), nullable=False, unique=True, index=True)
    label = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    # allow admins to supply a simple Jinja-based template that will be
    # rendered when notifications are sent to users primarily associated with
    # this department.  Keeping it on the department object keeps the UI
    # lightweight and prevents needing a separate configuration table.
    notification_template = db.Column(db.Text, nullable=True)
    handoff_template_doc_url = db.Column(db.String(500), nullable=True)
    handoff_template_checklist_json = db.Column(db.Text, nullable=True)

    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    order = db.Column(db.Integer, nullable=False, default=0)

    @property
    def name(self):
        return self.label

    @name.setter
    def name(self, v):
        self.label = v

    @property
    def handoff_template_checklist(self) -> list[str]:
        try:
            parsed = json.loads(self.handoff_template_checklist_json or "[]")
        except Exception:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(item or "").strip() for item in parsed if str(item or "").strip()]

    @handoff_template_checklist.setter
    def handoff_template_checklist(self, values):
        cleaned = [str(item or "").strip()[:255] for item in (values or []) if str(item or "").strip()]
        self.handoff_template_checklist_json = json.dumps(cleaned)


class StatusOption(TenantScopedMixin, db.Model):
    """Admin-manageable metadata for status selections.

    Each row corresponds to a status code and can control where the
    request should route (target department) and whether notifications
    should be emitted only when the transition results in a department
    transfer.

    New fields added in 2026-03 allow administrators to tune the automated
    nudge behaviour per-status.  The `nudge_level` column is an integer
    where:
      * 0 – do not participate in automated nudges
      * 1 – nudge every hour
      * 2 – nudge every four hours
      * 3 – nudge once per day
    The default for existing rows is zero (no nudges).
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
    # integer value describing how frequently this status should generate
    # automated nudges; see class docstring for meaning.
    nudge_level = db.Column(db.Integer, nullable=False, default=0)
    # JSON list of approval stages for this status. Each stage is stored as:
    # {"name": str, "role": str|None, "department": str|None}
    approval_stages_json = db.Column(db.Text, nullable=True)

    @staticmethod
    def normalize_approval_stages(value) -> list:
        if not value:
            return []

        raw_items = value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                raw_items = parsed if isinstance(parsed, list) else []
            except Exception:
                raw_items = []

        if not isinstance(raw_items, list):
            return []

        normalized = []
        for idx, item in enumerate(raw_items):
            if isinstance(item, str):
                name = item.strip()
                role = None
                department = None
            elif isinstance(item, dict):
                name = str(item.get("name") or item.get("label") or item.get("title") or "").strip()
                role = str(item.get("role") or "").strip().lower() or None
                department = str(item.get("department") or item.get("dept") or "").strip().upper() or None
            else:
                continue

            if not name:
                name = f"Stage {idx + 1}"
            if department and department not in {"A", "B", "C"}:
                department = None
            normalized.append(
                {
                    "name": name,
                    "role": role,
                    "department": department,
                }
            )
        return normalized

    @property
    def approval_stages(self) -> list:
        return self.normalize_approval_stages(self.approval_stages_json)

    @approval_stages.setter
    def approval_stages(self, value):
        self.approval_stages_json = json.dumps(self.normalize_approval_stages(value))

    @property
    def approval_stage_summary(self) -> str:
        stages = self.approval_stages
        if not stages:
            return "No stages"
        return ", ".join(stage.get("name") or f"Stage {idx + 1}" for idx, stage in enumerate(stages))


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
    """Per-department edit privileges assigned to users by admins.

    In addition to existing flags, department editors may now be granted
    the ability to change priority on requests belonging to their
    department.  This is represented by ``can_change_priority``.
    """

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", backref="dept_editor_roles")
    department = db.Column(db.String(2), nullable=False, index=True)
    can_edit = db.Column(db.Boolean, nullable=False, default=True)
    can_view_metrics = db.Column(db.Boolean, nullable=False, default=False)
    # department head may reassign the priority of requests in this dept
    can_change_priority = db.Column(db.Boolean, nullable=False, default=False)
    managed_by_profile = db.Column(db.Boolean, nullable=False, default=False)
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
    assignment_kind = db.Column(db.String(20), nullable=False, default="shared")
    note = db.Column(db.String(255), nullable=True)
    handoff_doc_url = db.Column(db.String(500), nullable=True)
    handoff_checklist_json = db.Column(db.Text, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint("user_id", "department", name="uq_user_department"),
    )

    @property
    def is_temporary(self) -> bool:
        return str(getattr(self, "assignment_kind", "shared") or "shared").strip().lower() == "temporary"

    @property
    def is_expired(self) -> bool:
        expires_at = getattr(self, "expires_at", None)
        if not expires_at:
            return False
        return expires_at <= datetime.utcnow()

    @property
    def is_active_assignment(self) -> bool:
        return not self.is_expired

    @property
    def handoff_checklist(self) -> list[str]:
        try:
            parsed = json.loads(self.handoff_checklist_json or "[]")
        except Exception:
            return []
        if not isinstance(parsed, list):
            return []
        cleaned = []
        for item in parsed:
            text = str(item or "").strip()
            if text:
                cleaned.append(text)
        return cleaned

    @handoff_checklist.setter
    def handoff_checklist(self, values):
        cleaned = []
        for item in values or []:
            text = str(item or "").strip()
            if text:
                cleaned.append(text[:255])
        self.handoff_checklist_json = json.dumps(cleaned)


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
