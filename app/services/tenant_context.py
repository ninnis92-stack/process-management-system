from __future__ import annotations

from typing import Iterable

from flask import g, has_request_context, session
from flask_login import current_user
from sqlalchemy import event, or_
from sqlalchemy.orm import Session, with_loader_criteria

from ..extensions import db
from ..models import (
	AuditLog,
	Department,
	DepartmentEditor,
	DepartmentFormAssignment,
	EmailRouting,
	FeatureFlags,
	FormTemplate,
	GuestForm,
	IntegrationConfig,
	IntegrationEvent,
	JobRecord,
	MetricsConfig,
	Notification,
	NotificationRetention,
	ProcessMetricEvent,
	RejectRequestConfig,
	Request,
	SiteConfig,
	SpecialEmailConfig,
	StatusBucket,
	StatusOption,
	Tenant,
	TenantMembership,
	TenantScopedMixin,
	User,
	UserDepartment,
	WebhookSubscription,
	Workflow,
)


TENANT_PERMISSION_MATRIX = {
	"platform_admin": {"admin", "manage_users", "manage_workflows", "view_metrics", "manage_billing"},
	"tenant_admin": {"admin", "manage_users", "manage_workflows", "view_metrics", "manage_billing"},
	"analyst": {"view_metrics", "manage_workflows"},
	"member": set(),
	"viewer": set(),
}


_TENANT_EVENTS_REGISTERED = False


def _session_tenant_id() -> int | None:
	if not has_request_context():
		return None
	try:
		raw = session.get("active_tenant_id")
		return int(raw) if raw is not None else None
	except Exception:
		return None


def get_current_tenant_id() -> int | None:
	if has_request_context():
		tenant_id = getattr(g, "current_tenant_id", None)
		if tenant_id is not None:
			return tenant_id
		tenant_id = _session_tenant_id()
		if tenant_id is not None:
			return tenant_id
		try:
			if getattr(current_user, "is_authenticated", False):
				user_tenant = getattr(current_user, "tenant_id", None)
				if user_tenant is not None:
					return int(user_tenant)
		except Exception:
			return None
	return None


def get_current_tenant() -> Tenant | None:
	tenant_id = get_current_tenant_id()
	if tenant_id is None:
		return None
	try:
		return db.session.get(Tenant, tenant_id)
	except Exception:
		return None


def ensure_default_tenant() -> Tenant:
	tenant = Tenant.query.filter_by(slug="default").first()
	if tenant:
		return tenant
	tenant = Tenant(name="Default Workspace", slug="default")
	db.session.add(tenant)
	try:
		db.session.commit()
	except Exception:
		db.session.rollback()
	return tenant


def ensure_user_tenant_membership(user: User | None) -> Tenant | None:
	if not user:
		return None
	tenant = ensure_default_tenant()
	changed = False
	if getattr(user, "tenant_id", None) is None:
		user.tenant_id = tenant.id
		changed = True

	membership = TenantMembership.query.filter_by(user_id=user.id, tenant_id=tenant.id).first()
	if not membership:
		membership = TenantMembership(
			user_id=user.id,
			tenant_id=tenant.id,
			role="tenant_admin" if getattr(user, "is_admin", False) else "member",
			is_default=True,
		)
		db.session.add(membership)
		changed = True
	elif getattr(user, "is_admin", False) and membership.role not in {"tenant_admin", "platform_admin"}:
		membership.role = "tenant_admin"
		changed = True

	if changed:
		db.session.add(user)
		try:
			db.session.commit()
		except Exception:
			db.session.rollback()
	return tenant


def get_user_membership(user: User | None, tenant_id: int | None = None) -> TenantMembership | None:
	if not user:
		return None
	target_id = tenant_id or get_current_tenant_id() or getattr(user, "tenant_id", None)
	if target_id is None:
		return None
	try:
		return TenantMembership.query.filter_by(user_id=user.id, tenant_id=target_id, is_active=True).first()
	except Exception:
		return None


def tenant_role_for_user(user: User | None, tenant_id: int | None = None) -> str | None:
	membership = get_user_membership(user, tenant_id=tenant_id)
	if membership:
		return membership.role
	if user and getattr(user, "is_admin", False):
		return "tenant_admin"
	return None


def user_has_permission(user: User | None, permission: str, tenant_id: int | None = None) -> bool:
	role = tenant_role_for_user(user, tenant_id=tenant_id)
	if not role:
		return False
	allowed = TENANT_PERMISSION_MATRIX.get(role, set())
	return permission in allowed or "admin" in allowed


def user_can_access_tenant(user: User | None, tenant_id: int | None) -> bool:
	if not user or tenant_id is None:
		return False
	membership = get_user_membership(user, tenant_id=tenant_id)
	return bool(membership)


def set_active_tenant(tenant: Tenant | int | None) -> None:
	if not has_request_context():
		return
	tenant_id = tenant.id if isinstance(tenant, Tenant) else tenant
	if tenant_id is None:
		return
	session["active_tenant_id"] = int(tenant_id)
	g.current_tenant_id = int(tenant_id)
	try:
		g.current_tenant = db.session.get(Tenant, int(tenant_id))
	except Exception:
		g.current_tenant = None


def _resolve_active_tenant_for_request() -> Tenant:
	default_tenant = ensure_default_tenant()
	active_id = _session_tenant_id()
	if getattr(current_user, "is_authenticated", False):
		ensure_user_tenant_membership(current_user)
		if active_id and user_can_access_tenant(current_user, active_id):
			tenant = db.session.get(Tenant, active_id)
			if tenant:
				return tenant
		default_membership = (
			TenantMembership.query.filter_by(user_id=current_user.id, is_default=True, is_active=True)
			.order_by(TenantMembership.created_at.asc())
			.first()
		)
		if default_membership:
			session["active_tenant_id"] = default_membership.tenant_id
			tenant = db.session.get(Tenant, default_membership.tenant_id)
			if tenant:
				return tenant
		session["active_tenant_id"] = default_tenant.id
		return default_tenant
	if active_id:
		tenant = db.session.get(Tenant, active_id)
		if tenant:
			return tenant
	session["active_tenant_id"] = default_tenant.id
	return default_tenant


def _tenant_scoped_models() -> Iterable[type]:
	return (
		User,
		Notification,
		WebhookSubscription,
		ProcessMetricEvent,
		MetricsConfig,
		Request,
		FormTemplate,
		GuestForm,
		DepartmentFormAssignment,
		SpecialEmailConfig,
		FeatureFlags,
		RejectRequestConfig,
		StatusBucket,
		AuditLog,
		SiteConfig,
		Department,
		StatusOption,
		Workflow,
		DepartmentEditor,
		UserDepartment,
		IntegrationConfig,
		NotificationRetention,
		EmailRouting,
		JobRecord,
		IntegrationEvent,
	)


def init_tenant_context(app) -> None:
	global _TENANT_EVENTS_REGISTERED

	if getattr(app, "_tenant_context_initialized", False):
		return

	@app.before_request
	def _bind_current_tenant():
		tenant = _resolve_active_tenant_for_request()
		g.current_tenant = tenant
		g.current_tenant_id = getattr(tenant, "id", None)

	@app.context_processor
	def _tenant_template_context():
		tenant = get_current_tenant()
		membership = None
		try:
			if getattr(current_user, "is_authenticated", False):
				membership = get_user_membership(current_user, getattr(tenant, "id", None))
		except Exception:
			membership = None
		return {
			"current_tenant": tenant,
			"current_tenant_membership": membership,
			"current_tenant_role": getattr(membership, "role", None),
		}

	if not _TENANT_EVENTS_REGISTERED:
		@event.listens_for(Session, "do_orm_execute")
		def _apply_tenant_scope(execute_state):
			if not execute_state.is_select:
				return
			if execute_state.execution_options.get("skip_tenant_scope"):
				return
			tenant_id = get_current_tenant_id()
			if tenant_id is None:
				return
			execute_state.statement = execute_state.statement.options(
				with_loader_criteria(
					TenantScopedMixin,
						lambda cls: or_(cls.tenant_id == tenant_id, cls.tenant_id.is_(None)),
					include_aliases=True,
				)
			)

		@event.listens_for(Session, "before_flush")
		def _assign_tenant_before_flush(session_obj, flush_context, instances):
			tenant_id = get_current_tenant_id()
			if tenant_id is None:
				return
			for obj in session_obj.new:
				if isinstance(obj, TenantScopedMixin) and getattr(obj, "tenant_id", None) is None:
					obj.tenant_id = tenant_id

		_TENANT_EVENTS_REGISTERED = True

	app._tenant_context_initialized = True
