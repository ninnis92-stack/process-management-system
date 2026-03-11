from flask import flash, jsonify, redirect, render_template
from flask import request as flask_request
from flask import url_for
from flask_login import login_required

from ..extensions import db, get_or_404
from ..models import AutomationRule
from .forms import AutomationRuleForm
from .routes import admin_bp
from .utils import _is_admin_user


@admin_bp.route("/automation_rules")
@admin_bp.route("/automation_rules/")
@login_required
def list_automation_rules():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    rules = AutomationRule.query.order_by(AutomationRule.name.asc()).all()
    return render_template("admin_automation_rules.html", rules=rules)


@admin_bp.route("/automation_rules/new", methods=["GET", "POST"])
@login_required
def create_automation_rule():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    form = AutomationRuleForm()
    if form.validate_on_submit():
        import json

        triggers = [
            line.strip()
            for line in (form.triggers.data or "").splitlines()
            if line.strip()
        ]
        try:
            conditions = (
                json.loads(form.conditions.data) if form.conditions.data else {}
            )
        except Exception:
            flash("Invalid JSON for conditions.", "danger")
            return render_template("admin_automation_rule_form.html", form=form)
        try:
            actions = json.loads(form.actions.data) if form.actions.data else []
        except Exception:
            flash("Invalid JSON for actions.", "danger")
            return render_template("admin_automation_rule_form.html", form=form)
        r = AutomationRule(
            name=form.name.data.strip(),
            description=(form.description.data or "").strip() or None,
            triggers_json=triggers,
            conditions_json=conditions,
            actions_json=actions,
            is_active=bool(form.is_active.data),
        )
        db.session.add(r)
        db.session.commit()
        flash("Automation rule created.", "success")
        return redirect(url_for("admin.list_automation_rules"))
    return render_template("admin_automation_rule_form.html", form=form)


@admin_bp.route("/automation_rules/<int:rule_id>/edit", methods=["GET", "POST"])
@login_required
def edit_automation_rule(rule_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    r = get_or_404(AutomationRule, rule_id)
    form = AutomationRuleForm(obj=r)
    if flask_request.method == "GET":
        form.triggers.data = "\n".join(r.triggers_json or [])
        import json

        form.conditions.data = json.dumps(r.conditions_json or {}, indent=2)
        form.actions.data = json.dumps(r.actions_json or [], indent=2)
    if form.validate_on_submit():
        import json

        r.name = form.name.data.strip()
        r.description = (form.description.data or "").strip() or None
        r.triggers_json = [
            line.strip()
            for line in (form.triggers.data or "").splitlines()
            if line.strip()
        ]
        try:
            r.conditions_json = (
                json.loads(form.conditions.data) if form.conditions.data else {}
            )
        except Exception:
            flash("Invalid JSON for conditions.", "danger")
            return render_template("admin_automation_rule_form.html", form=form, rule=r)
        try:
            r.actions_json = json.loads(form.actions.data) if form.actions.data else []
        except Exception:
            flash("Invalid JSON for actions.", "danger")
            return render_template("admin_automation_rule_form.html", form=form, rule=r)
        r.is_active = bool(form.is_active.data)
        db.session.commit()
        flash("Automation rule updated.", "success")
        return redirect(url_for("admin.list_automation_rules"))
    return render_template("admin_automation_rule_form.html", form=form, rule=r)


@admin_bp.route("/automation_rules/<int:rule_id>/delete", methods=["POST"])
@login_required
def delete_automation_rule(rule_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    r = get_or_404(AutomationRule, rule_id)
    db.session.delete(r)
    db.session.commit()
    flash("Automation rule deleted.", "success")
    return redirect(url_for("admin.list_automation_rules"))
