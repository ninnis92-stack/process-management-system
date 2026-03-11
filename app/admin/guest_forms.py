from typing import Optional

from flask import flash, redirect, render_template, url_for
from flask_login import login_required

from ..extensions import db, get_or_404
from ..models import FormTemplate, GuestForm
from .forms import GuestFormAdminForm
from .routes import admin_bp
from .utils import _is_admin_user


def _guest_form_template_choices():
    templates = FormTemplate.query.order_by(FormTemplate.name.asc()).all()
    return [(0, "-- none --")] + [(t.id, t.name) for t in templates]


def _guest_form_from_form(
    form: GuestFormAdminForm, guest_form: Optional[GuestForm] = None
):
    guest_form = guest_form or GuestForm()
    guest_form.name = form.name.data.strip()
    guest_form.slug = form.slug.data.strip()
    guest_form.template_id = (form.template_id.data or None) or None
    guest_form.access_policy = form.access_policy.data or "public"
    guest_form.require_sso = bool(
        guest_form.access_policy in {"sso_linked", "approved_sso_domains"}
    )
    guest_form.allowed_email_domains = (
        form.allowed_email_domains.data or ""
    ).strip() or None
    guest_form.credential_requirements_json = (
        form.credential_requirements_json.data or ""
    ).strip() or None
    guest_form.owner_department = form.owner_department.data or "B"
    guest_form.layout = form.layout.data or "standard"
    guest_form.is_default = bool(form.is_default.data)
    guest_form.active = bool(form.active.data)
    return guest_form


def _populate_guest_form_form(form: GuestFormAdminForm, guest_form: GuestForm):
    form.template_id.choices = _guest_form_template_choices()
    form.template_id.data = guest_form.template_id or 0
    form.owner_department.data = guest_form.owner_department or "B"
    if not form.is_submitted():
        form.access_policy.data = guest_form.normalized_access_policy
        form.allowed_email_domains.data = guest_form.allowed_email_domains or ""
        form.credential_requirements_json.data = (
            guest_form.credential_requirements_pretty_json
        )
        form.layout.data = guest_form.layout or "standard"


def _apply_guest_form_default_flag(guest_form: GuestForm):
    if guest_form.is_default:
        try:
            GuestForm.query.update({GuestForm.is_default: False})
            db.session.flush()
        except Exception:
            db.session.rollback()
        guest_form.is_default = True


@admin_bp.route("/guest_forms")
@login_required
def list_guest_forms():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    forms = GuestForm.query.order_by(GuestForm.created_at.desc()).all()
    return render_template("admin_guest_forms.html", forms=forms)


@admin_bp.route("/guest_forms/new", methods=["GET", "POST"])
@login_required
def create_guest_form():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    form = GuestFormAdminForm()
    form.template_id.choices = _guest_form_template_choices()

    if form.validate_on_submit():
        guest_form = _guest_form_from_form(form)
        _apply_guest_form_default_flag(guest_form)
        db.session.add(guest_form)
        try:
            db.session.commit()
            flash("Guest request form created.", "success")
            return redirect(url_for("admin.list_guest_forms"))
        except Exception:
            db.session.rollback()
            flash("Failed to create guest request form.", "danger")

    return render_template("admin_guest_form_edit.html", form=form)


@admin_bp.route("/guest_forms/<int:gf_id>/edit", methods=["GET", "POST"])
@login_required
def edit_guest_form(gf_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    guest_form = get_or_404(GuestForm, gf_id)
    form = GuestFormAdminForm(obj=guest_form)
    _populate_guest_form_form(form, guest_form)

    if form.validate_on_submit():
        guest_form = _guest_form_from_form(form, guest_form)
        _apply_guest_form_default_flag(guest_form)
        try:
            db.session.commit()
            flash("Guest request form updated.", "success")
            return redirect(url_for("admin.list_guest_forms"))
        except Exception:
            db.session.rollback()
            flash("Failed to update guest request form.", "danger")

    return render_template("admin_guest_form_edit.html", form=form, edit=guest_form)


@admin_bp.route("/guest_forms/<int:gf_id>/delete", methods=["POST"])
@login_required
def delete_guest_form(gf_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    guest_form = get_or_404(GuestForm, gf_id)
    try:
        db.session.delete(guest_form)
        db.session.commit()
        flash("Guest request form deleted.", "success")
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        flash("Failed to delete guest request form.", "danger")
    return redirect(url_for("admin.list_guest_forms"))
