from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required

from ..extensions import db, get_or_404
from ..models import Tenant, TenantMembership, User
from .forms import TenantForm, TenantMembershipForm
from .routes import admin_bp
from .utils import _is_admin_user


@admin_bp.route("/tenants")
@login_required
def tenant_overview():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    tenants = Tenant.query.order_by(Tenant.created_at.asc()).all()
    memberships = TenantMembership.query.order_by(
        TenantMembership.created_at.desc()
    ).all()
    return render_template(
        "admin_tenants.html", tenants=tenants, memberships=memberships
    )


@admin_bp.route("/tenants/new", methods=["GET", "POST"])
@login_required
def create_tenant():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    form = TenantForm()
    if form.validate_on_submit():
        slug = form.slug.data.strip().lower()
        name = form.name.data.strip()
        active = bool(form.is_active.data)

        existing = Tenant.query.filter_by(slug=slug).first()
        if existing:
            existing.name = name
            existing.is_active = active
            db.session.commit()
            flash(f"Tenant '{slug}' updated.", "success")
            return redirect(url_for("admin.tenant_overview"))

        tenant = Tenant(slug=slug, name=name, is_active=active)
        db.session.add(tenant)
        db.session.commit()
        flash(f"Tenant '{slug}' created.", "success")
        return redirect(url_for("admin.tenant_overview"))

    return render_template("admin_tenant_form.html", form=form)


@admin_bp.route("/tenants/<int:tenant_id>/edit", methods=["GET", "POST"])
@login_required
def edit_tenant(tenant_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    tenant = get_or_404(Tenant, tenant_id)
    form = TenantForm(obj=tenant)
    if form.validate_on_submit():
        tenant.slug = form.slug.data.strip().lower()
        tenant.name = form.name.data.strip()
        tenant.is_active = bool(form.is_active.data)
        db.session.commit()
        flash("Tenant updated.", "success")
        return redirect(url_for("admin.tenant_overview"))
    return render_template("admin_tenant_form.html", form=form, tenant=tenant)


@admin_bp.route("/tenants/<int:tenant_id>/delete", methods=["POST"])
@login_required
def delete_tenant(tenant_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    tenant = get_or_404(Tenant, tenant_id)
    try:
        db.session.delete(tenant)
        db.session.commit()
        flash("Tenant deleted.", "success")
    except Exception:
        db.session.rollback()
        flash("Failed to delete tenant.", "danger")
    return redirect(url_for("admin.tenant_overview"))


# membership management
@admin_bp.route("/tenants/<int:tenant_id>/members", methods=["GET", "POST"])
@login_required
def tenant_members(tenant_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    tenant = get_or_404(Tenant, tenant_id)
    form = TenantMembershipForm()
    form.user_id.choices = [
        (u.id, u.email) for u in User.query.order_by(User.email).all()
    ]

    if form.validate_on_submit():
        user_id = form.user_id.data
        role = form.role.data
        active = bool(form.is_active.data)
        membership = TenantMembership.query.filter_by(
            tenant_id=tenant_id, user_id=user_id
        ).first()
        if not membership:
            membership = TenantMembership(tenant_id=tenant_id, user_id=user_id)
        membership.role = role
        membership.is_active = active
        db.session.add(membership)
        db.session.commit()
        flash("Membership saved.", "success")
        return redirect(url_for("admin.tenant_members", tenant_id=tenant_id))

    memberships = TenantMembership.query.filter_by(tenant_id=tenant_id).all()
    return render_template(
        "admin_tenant_members.html", tenant=tenant, memberships=memberships, form=form
    )


@admin_bp.route(
    "/tenants/<int:tenant_id>/members/<int:member_id>/delete", methods=["POST"]
)
@login_required
def delete_tenant_member(tenant_id: int, member_id: int):
    if not _is_admin_user():
        return redirect(url_for("requests.dashboard"))
    membership = get_or_404(TenantMembership, member_id)
    try:
        db.session.delete(membership)
        db.session.commit()
        flash("Membership removed.", "success")
    except Exception:
        db.session.rollback()
        flash("Unable to remove membership.", "danger")
    return redirect(url_for("admin.tenant_members", tenant_id=tenant_id))
