from flask import (
    render_template,
    redirect,
    url_for,
    flash,
    current_app,
    jsonify,
    request as flask_request,
)
from flask_login import login_required
from .utils import _is_admin_user

from ..extensions import db, get_or_404
from ..models import (
    Workflow,
    StatusOption,
    StatusBucket,
    BucketStatus,
)
from .routes import admin_bp
from .forms import WorkflowForm, StatusBucketForm, StatusOptionForm
from ..requests_bp.workflow import (
    owner_for_status,
    workflow_editor_sections,
    workflow_intake_preview,
)


# Helper logic related to workflows and status options, extracted from
# the monolithic routes.py.  Keeping these private to this module.

def _normalize_department_code(value):
    raw = (value or "").strip()
    if not raw:
        return ""
    upper = raw.upper()
    if upper in {"A", "B", "C"}:
        return upper
    compact = upper.replace("DEPARTMENT", "").replace("DEPT", "").strip()
    return compact if compact in {"A", "B", "C"} else ""


def _default_workflow_spec():
    steps = [
        {"from_dept": "A", "to_dept": "B", "status": "NEW_FROM_A"},
        {"from_dept": "B", "to_dept": "B", "status": "B_IN_PROGRESS"},
        {"from_dept": "B", "to_dept": "C", "status": "PENDING_C_REVIEW"},
        {"from_dept": "C", "to_dept": "B", "status": "B_FINAL_REVIEW"},
        {"from_dept": "B", "to_dept": "A", "status": "SENT_TO_A"},
        {"from_dept": "A", "to_dept": "B", "status": "CLOSED"},
    ]
    transitions = []
    for i in range(len(steps) - 1):
        transitions.append(
            {
                "from": steps[i]["status"],
                "to": steps[i + 1]["status"],
                "from_status": steps[i]["status"],
                "to_status": steps[i + 1]["status"],
                "from_dept": steps[i].get("to_dept") or steps[i].get("from_dept"),
                "to_dept": steps[i + 1].get("to_dept") or steps[i + 1].get("from_dept"),
            }
        )
    return {"steps": steps, "transitions": transitions}


def _normalize_workflow_spec(spec, workflow_name=None):
    if not isinstance(spec, dict):
        return spec

    steps = spec.get("steps") or []
    if not steps:
        return spec
    if any(
        isinstance(step, dict) and (step.get("from_dept") or step.get("to_dept"))
        for step in steps
    ):
        return spec

    statuses = [str(step).strip() for step in steps if isinstance(step, str) and step.strip()]
    if not statuses:
        return spec

    default_statuses = [step["status"] for step in _default_workflow_spec()["steps"]]
    if statuses == default_statuses:
        # the spec is already the default; just return it unchanged so the
        # UI doesn't show redundant department fields.
        return spec

    # when migrating from old spec format the step labels might be simple
    # strings; transform those into objects so the rest of the code expects a
    # uniform shape.
    normalized = {"steps": [], "transitions": []}
    for step in steps:
        if isinstance(step, str):
            normalized["steps"].append({"status": step})
        elif isinstance(step, dict):
            normalized["steps"].append(step)
    # transitions in the old format were simply two-element lists.  convert them
    # to dicts as well so callers don't need to handle both shapes.
    old_trans = spec.get("transitions") or []
    for t in old_trans:
        if isinstance(t, list) and len(t) == 2:
            normalized["transitions"].append({"from": t[0], "to": t[1]})
        elif isinstance(t, dict):
            normalized["transitions"].append(t)
    return normalized


def _build_status_options_map(wf=None):
    # return a mapping of status code -> StatusOption object so the workflows
    # UI can label steps with existing option labels if available.
    opts = {o.code: o for o in StatusOption.query.all()}
    # if a workflow is provided we also want to ensure any codes it references
    # are at least present as `StatusOption` objects in the map (without
    # necessarily persisting them yet).
    if wf and wf.spec:
        spec = _normalize_workflow_spec(wf.spec, wf.name)
        for step in spec.get("steps") or []:
            code = None
            if isinstance(step, str):
                code = step
            elif isinstance(step, dict):
                code = step.get("status") or step.get("code")
            if code and code not in opts:
                # create a temporary placeholder
                opts[code] = StatusOption(code=code, label=code.replace("_", " ").title())
    return opts


def _workflow_scope_label(wf):
    dept = _normalize_department_code(wf.department_code)
    if dept:
        return f"Dept {dept}"
    return "All departments"


def _parse_approval_stage_lines(raw_text):
    stages = []
    for line in (raw_text or "").splitlines():
        trimmed = line.strip()
        if not trimmed:
            continue
        parts = [part.strip() for part in trimmed.split("|")]
        name = parts[0] if parts else ""
        role = (parts[1] if len(parts) > 1 else "").lower() or None
        department = (parts[2] if len(parts) > 2 else "").upper() or None
        if department and department not in {"A", "B", "C"}:
            department = None
        if not name:
            continue
        stages.append({"name": name, "role": role, "department": department})
    return stages


def _format_approval_stage_lines(opt):
    lines = []
    for stage in getattr(opt, "approval_stages", []) or []:
        parts = [stage.get("name") or "Stage"]
        if stage.get("role"):
            parts.append(stage.get("role"))
        if stage.get("department"):
            if len(parts) == 1:
                parts.append("")
            parts.append(stage.get("department"))
        lines.append(" | ".join(parts))
    return "\n".join(lines)


# --- workflow CRUD -----------------------------------------------------------

@admin_bp.route("/workflows")
@login_required

def list_workflows():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    wfs = Workflow.query.order_by(Workflow.name.asc()).all()
    workflow_scope_labels = {wf.id: _workflow_scope_label(wf) for wf in wfs}
    return render_template(
        "admin_workflows.html",
        workflows=wfs,
        workflow_scope_labels=workflow_scope_labels,
    )


@admin_bp.route("/workflows/new", methods=["GET", "POST"])
@login_required

def create_workflow():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    form = WorkflowForm()
    if form.validate_on_submit():
        wf = Workflow(
            name=form.name.data.strip(),
            description=(form.description.data or "").strip() or None,
            department_code=(form.department_code.data or None) or None,
            spec=None,
            active=bool(form.active.data),
        )
        # attempt to parse JSON if provided, otherwise accept steps[] fallback
        import json

        if form.spec_json.data:
            try:
                wf.spec = json.loads(form.spec_json.data)
            except Exception:
                flash("Invalid JSON for workflow spec.", "danger")
                return render_template("admin_workflow_form.html", form=form)
        else:
            steps = flask_request.form.getlist("steps[]") or flask_request.form.getlist(
                "steps"
            )
            if steps:
                steps = [s.strip() for s in steps if s and s.strip()]
                transitions = []
                for i in range(len(steps) - 1):
                    transitions.append({"from": steps[i], "to": steps[i + 1]})
                wf.spec = {"steps": steps, "transitions": transitions}
        db.session.add(wf)
        db.session.commit()
        action = flask_request.form.get('action') or 'save'
        # If admin chose to implement, create any missing StatusOption rows
        if action == 'implement':
            try:
                from ..models import StatusOption

                steps = []
                if isinstance(wf.spec, dict):
                    steps = wf.spec.get('steps') or []
                for s in steps:
                    code = None
                    target_dept = None
                    if isinstance(s, str):
                        code = s
                    elif isinstance(s, dict):
                        code = s.get('status') or s.get('code')
                        target_dept = s.get('to_dept') or s.get('to')
                    if not code:
                        continue
                    existing = StatusOption.query.filter_by(code=code).first()
                    if not existing:
                        label = code.replace('_', ' ').title()
                        opt = StatusOption(code=code, label=label)
                        if target_dept:
                            opt.target_department = target_dept or None
                        db.session.add(opt)
                db.session.commit()
                flash('Workflow created and status options implemented.', 'success')
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                flash('Workflow created but failed to implement status options.', 'warning')
            return redirect(url_for('admin.list_workflows'))
        flash("Workflow created.", "success")
        return redirect(url_for("admin.list_workflows"))
    return render_template(
        "admin_workflow_form.html",
        form=form,
        status_options_map=_build_status_options_map(),
        editor_sections=workflow_editor_sections(None),
        workflow_preview=workflow_intake_preview(None),
    )


@admin_bp.route("/workflows/<int:wf_id>/edit", methods=["GET", "POST"])
@login_required

def edit_workflow(wf_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    wf = get_or_404(Workflow, wf_id)
    form = WorkflowForm(obj=wf)
    # prefill spec_json
    if flask_request.method == "GET" and wf.spec is not None:
        import json

        try:
            form.spec_json.data = json.dumps(
                _normalize_workflow_spec(wf.spec, wf.name), indent=2
            )
        except Exception:
            form.spec_json.data = str(wf.spec)

    if form.validate_on_submit():
        wf.name = form.name.data.strip()
        wf.description = (form.description.data or "").strip() or None
        wf.department_code = (form.department_code.data or None) or None
        wf.active = bool(form.active.data)
        if form.spec_json.data:
            import json

            try:
                wf.spec = json.loads(form.spec_json.data)
            except Exception:
                flash("Invalid JSON for workflow spec.", "danger")
                return render_template("admin_workflow_form.html", form=form, wf=wf)
        else:
            steps = flask_request.form.getlist("steps[]") or flask_request.form.getlist(
                "steps"
            )
            if steps:
                steps = [s.strip() for s in steps if s and s.strip()]
                transitions = []
                for i in range(len(steps) - 1):
                    transitions.append({"from": steps[i], "to": steps[i + 1]})
                wf.spec = {"steps": steps, "transitions": transitions}
            else:
                wf.spec = None
        db.session.commit()
        action = flask_request.form.get('action') or 'save'
        if action == 'implement':
            try:
                from ..models import StatusOption

                steps = []
                if isinstance(wf.spec, dict):
                    steps = wf.spec.get('steps') or []
                for s in steps:
                    code = None
                    target_dept = None
                    if isinstance(s, str):
                        code = s
                    elif isinstance(s, dict):
                        code = s.get('status') or s.get('code')
                        target_dept = s.get('to_dept') or s.get('to')
                    if not code:
                        continue
                    existing = StatusOption.query.filter_by(code=code).first()
                    if not existing:
                        label = code.replace('_', ' ').title()
                        opt = StatusOption(code=code, label=label)
                        if target_dept:
                            opt.target_department = target_dept or None
                        db.session.add(opt)
                db.session.commit()
                flash('Workflow updated and status options implemented.', 'success')
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                flash('Workflow updated but failed to implement status options.', 'warning')
            return redirect(url_for('admin.list_workflows'))
        flash("Workflow updated.", "success")
        return redirect(url_for("admin.list_workflows"))
    return render_template(
        "admin_workflow_form.html",
        form=form,
        wf=wf,
        editor_spec=_normalize_workflow_spec(wf.spec, wf.name),
        status_options_map=_build_status_options_map(wf),
        editor_sections=workflow_editor_sections(_normalize_workflow_spec(wf.spec, wf.name), wf.department_code),
        workflow_preview=workflow_intake_preview(wf, wf.department_code),
    )


@admin_bp.route("/workflows/<int:wf_id>/delete", methods=["POST"])
@login_required

def delete_workflow(wf_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    wf = get_or_404(Workflow, wf_id)
    db.session.delete(wf)
    db.session.commit()
    flash("Workflow deleted.", "success")
    return redirect(url_for("admin.list_workflows"))


@admin_bp.route("/workflows/<int:wf_id>/toggle", methods=["POST"])
@login_required

def toggle_workflow_active(wf_id: int):
    if not _is_admin_user():
        return jsonify({"error": "access_denied"}), 403
    wf = get_or_404(Workflow, wf_id)
    try:
        wf.active = not bool(wf.active)
        db.session.commit()
        return jsonify({"ok": True, "active": bool(wf.active)})
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({"ok": False}), 500


@admin_bp.route("/status_options")
@login_required

def list_status_options():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    # load existing options, but if none are present try to bootstrap from any
    # workflows that might exist.  this helps new installs or cases where the
    # workflow page has been used but the admin never clicked "implement".
    opts = []
    try:
        opts = StatusOption.query.order_by(StatusOption.code).all()
    except Exception:
        # Defensive: if DB schema is out-of-date (missing columns), avoid 500
        # and show an empty list with a helpful admin notice.
        current_app.logger.exception(
            "Failed to load StatusOption rows for admin list; DB schema may be missing migrations"
        )
        try:
            inspector = db.inspect(db.engine)
            table_name = StatusOption.__tablename__
            if not inspector.has_table(table_name):
                try:
                    StatusOption.__table__.create(bind=db.engine)
                    flash(
                        "Status options table was missing and has been created. Please run `alembic upgrade head` to synchronize migrations.",
                        "warning",
                    )
                except Exception:
                    current_app.logger.exception("Failed to create StatusOption table")
                    flash(
                        "Status options could not be loaded. Ensure DB migrations have been applied (run alembic upgrade head).",
                        "danger",
                    )
                opts = []
            else:
                existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
                model_cols = {c.name for c in StatusOption.__table__.columns}
                missing = model_cols - existing_cols
                if missing:
                    flash(
                        f"Status options schema mismatch: missing columns: {', '.join(sorted(missing))}. Run `alembic upgrade head`.",
                        "danger",
                    )
                else:
                    flash(
                        "Status options could not be loaded due to an unexpected database error. Check application logs for details.",
                        "danger",
                    )
                opts = []
        except Exception:
            current_app.logger.exception("Failed to inspect DB schema for StatusOption")
            flash(
                "Status options could not be loaded. Ensure DB migrations have been applied (run alembic upgrade head).",
                "danger",
            )
            opts = []

    # if the table exists but is currently empty, attempt to derive rows from any
    # existing workflows so the admin has something visible immediately.
    if not opts:
        try:
            generated = False
            for wf in Workflow.query.all():
                spec = _normalize_workflow_spec(wf.spec, wf.name)
                steps = spec.get("steps") or []
                for step in steps:
                    code = None
                    target_dept = None
                    if isinstance(step, dict):
                        code = step.get("status") or step.get("code")
                        target_dept = step.get("to_dept") or step.get("to")
                    elif isinstance(step, str):
                        code = step
                    if not code:
                        continue
                    if not StatusOption.query.filter_by(code=code).first():
                        label = code.replace("_", " ").title()
                        opt = StatusOption(code=code, label=label)
                        if target_dept:
                            opt.target_department = target_dept or None
                        db.session.add(opt)
                        generated = True
            if generated:
                db.session.commit()
                flash("Status options generated from existing workflows.", "info")
                opts = StatusOption.query.order_by(StatusOption.code).all()
        except Exception:
            # if something goes wrong here just log and continue with empty list
            current_app.logger.exception("Failed to bootstrap status options from workflows")

    return render_template("admin_status_options.html", status_options=opts)


@admin_bp.route("/status_options/new", methods=["GET", "POST"])
@login_required

def create_status_option():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    from .forms import StatusOptionForm

    form = StatusOptionForm()
    if form.validate_on_submit():
        code = form.code.data.strip()
        approval_stages = _parse_approval_stage_lines(
            getattr(form, "approval_stages_text", None).data
            if getattr(form, "approval_stages_text", None)
            else ""
        )
        opt = StatusOption(
            code=code,
            label=form.label.data.strip(),
            target_department=(form.target_department.data or None),
            notify_enabled=bool(form.notify_enabled.data),
            notify_on_transfer_only=bool(form.notify_on_transfer_only.data),
            notify_to_originator_only=bool(
                getattr(form, "notify_to_originator_only", False).data
                if getattr(form, "notify_to_originator_only", None)
                else False
            ),
            email_enabled=bool(
                getattr(form, "email_enabled", False).data
                if getattr(form, "email_enabled", None)
                else False
            ),
            screenshot_required=bool(
                getattr(form, "screenshot_required", False).data
                if getattr(form, "screenshot_required", None)
                else False
            ),
            nudge_level=int(form.nudge_level.data or 0),
        )
        opt.approval_stages = approval_stages
        db.session.add(opt)
        db.session.commit()
        flash("Status option created.", "success")
        return redirect(url_for("admin.list_status_options"))
    return render_template("admin_status_edit.html", form=form)


@admin_bp.route("/status_options/<int:opt_id>/edit", methods=["GET", "POST"])
@login_required

def edit_status_option(opt_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    from .forms import StatusOptionForm

    opt = get_or_404(StatusOption, opt_id)
    form = StatusOptionForm(obj=opt)
    if flask_request.method == "GET":
        if getattr(form, "approval_stages_text", None):
            form.approval_stages_text.data = _format_approval_stage_lines(opt)
        # ensure dropdown reflects numeric value as string
        if getattr(form, "nudge_level", None):
            form.nudge_level.data = str(getattr(opt, "nudge_level", 0) or 0)
    if form.validate_on_submit():
        opt.code = form.code.data.strip()
        opt.label = form.label.data.strip()
        opt.target_department = form.target_department.data or None
        opt.notify_enabled = bool(form.notify_enabled.data)
        opt.notify_on_transfer_only = bool(form.notify_on_transfer_only.data)
        opt.notify_to_originator_only = bool(
            getattr(form, "notify_to_originator_only", False).data
            if getattr(form, "notify_to_originator_only", None)
            else False
        )
        opt.email_enabled = bool(
            getattr(form, "email_enabled", False).data
            if getattr(form, "email_enabled", None)
            else False
        )
        opt.screenshot_required = bool(
            getattr(form, "screenshot_required", False).data
            if getattr(form, "screenshot_required", None)
            else False
        )
        opt.nudge_level = int(form.nudge_level.data or 0)
        opt.approval_stages = _parse_approval_stage_lines(
            getattr(form, "approval_stages_text", None).data
            if getattr(form, "approval_stages_text", None)
            else ""
        )
        db.session.commit()
        flash("Status option updated.", "success")
        return redirect(url_for("admin.list_status_options"))
    return render_template("admin_status_edit.html", form=form, opt=opt)


@admin_bp.route("/status_options/<int:opt_id>/delete", methods=["POST"])
@login_required

def delete_status_option(opt_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    opt = get_or_404(StatusOption, opt_id)
    db.session.delete(opt)
    db.session.commit()
    flash("Status option deleted.", "success")
    return redirect(url_for("admin.list_status_options"))


@admin_bp.route("/status_options/<int:opt_id>/toggle_screenshot", methods=["POST"])
@login_required

def toggle_status_screenshot(opt_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    opt = get_or_404(StatusOption, opt_id)
    try:
        opt.screenshot_required = not bool(opt.screenshot_required)
        db.session.commit()
        flash("Screenshot requirement updated.", "success")
    except Exception:
        db.session.rollback()
        flash("Failed to update screenshot requirement.", "danger")
    return redirect(url_for("admin.list_status_options"))


@admin_bp.route("/status_options/<int:opt_id>/toggle_notify_scope", methods=["POST"])
@login_required

def toggle_status_notify_scope(opt_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    opt = get_or_404(StatusOption, opt_id)
    try:
        opt.notify_to_originator_only = not bool(
            getattr(opt, "notify_to_originator_only", False)
        )
        db.session.commit()
        flash("Notification scope updated.", "success")
    except Exception:
        db.session.rollback()
        flash("Failed to update notification scope.", "danger")
    return redirect(url_for("admin.list_status_options"))


@admin_bp.route("/status_options/<int:opt_id>/toggle_email", methods=["POST"])
@login_required

def toggle_status_email(opt_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    opt = get_or_404(StatusOption, opt_id)
    try:
        opt.email_enabled = not bool(getattr(opt, "email_enabled", False))
        db.session.commit()
        flash("Email setting updated for that status.", "success")
    except Exception:
        db.session.rollback()
        flash("Failed to update email setting.", "danger")
    return redirect(url_for("admin.list_status_options"))


# --- buckets -----------------------------------------------------------------

@admin_bp.route("/buckets/import_default", methods=["POST"])
@login_required

def import_default_buckets():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    # Recommended default buckets for Dept B (used by tests)
    try:
        # Unassigned bucket (no statuses - catch-all filter applied at dashboard)
        ua = StatusBucket.query.filter_by(name="Unassigned", department_name="B").first()
        if not ua:
            ua = StatusBucket(name="Unassigned", department_name="B", order=0, active=True)
            db.session.add(ua)

        # In Progress bucket
        b = StatusBucket.query.filter_by(
            name="In Progress", department_name="B"
        ).first()
        if not b:
            b = StatusBucket(
                name="In Progress", department_name="B", order=1, active=True
            )
            db.session.add(b)
            db.session.flush()
            bs = BucketStatus(bucket_id=b.id, status_code="B_IN_PROGRESS", order=0)
            db.session.add(bs)

        # Waiting bucket
        w = StatusBucket.query.filter_by(name="Waiting", department_name="B").first()
        if not w:
            w = StatusBucket(name="Waiting", department_name="B", order=2, active=True)
            db.session.add(w)
            db.session.flush()
            ws = BucketStatus(
                bucket_id=w.id, status_code="WAITING_ON_A_RESPONSE", order=0
            )
            db.session.add(ws)

        db.session.commit()
        flash("Imported recommended buckets.", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to import default buckets")
        flash("Failed to import buckets.", "danger")
    return redirect(url_for("admin.list_departments"))


@admin_bp.route("/buckets")
@login_required

def list_buckets():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    buckets = StatusBucket.query.order_by(
        StatusBucket.department_name.asc().nullsfirst(), StatusBucket.order.asc()
    ).all()
    return render_template("admin_buckets.html", buckets=buckets)


@admin_bp.route("/buckets/new", methods=["GET", "POST"])
@login_required

def buckets_new():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    form = StatusBucketForm()
    # populate workflow choices (global + any department-scoped active workflows)
    wfs = (
        Workflow.query.filter(Workflow.active == True)
        .order_by(Workflow.name.asc())
        .all()
    )
    form.workflow_id.choices = [(0, "-- None --")] + [
        (w.id, w.name + (f" (Dept {w.department_code})" if w.department_code else ""))
        for w in wfs
    ]

    if form.validate_on_submit():
        b = StatusBucket(
            name=form.name.data.strip(),
            department_name=(form.department_name.data or None) or None,
            order=int(form.order.data or 0),
            active=bool(form.active.data),
        )
        # assign workflow if selected
        try:
            sel = int(form.workflow_id.data or 0)
        except Exception:
            sel = 0
        if sel:
            b.workflow_id = sel
        db.session.add(b)
        db.session.commit()
        flash("Bucket created.", "success")
        return redirect(url_for("admin.list_buckets"))
    return render_template("admin_bucket_form.html", form=form)


@admin_bp.route("/buckets/<int:bucket_id>/edit", methods=["GET", "POST"])
@login_required

def buckets_edit(bucket_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    b = get_or_404(StatusBucket, bucket_id)
    form = StatusBucketForm(obj=b)
    # populate workflow choices scoped to department (or global)
    if b.department_name:
        wfs = (
            Workflow.query.filter(
                (Workflow.department_code == None)
                | (Workflow.department_code == b.department_name)
            )
            .filter(Workflow.active == True)
            .order_by(Workflow.name.asc())
            .all()
        )
    else:
        wfs = (
            Workflow.query.filter(Workflow.active == True)
            .order_by(Workflow.name.asc())
            .all()
        )
    form.workflow_id.choices = [(0, "-- None --")] + [
        (w.id, w.name + (f" (Dept {w.department_code})" if w.department_code else ""))
        for w in wfs
    ]
    # prefill selected workflow in form when GET
    if flask_request.method == "GET":
        try:
            form.workflow_id.data = int(b.workflow_id) if b.workflow_id else 0
        except Exception:
            form.workflow_id.data = 0

    if form.validate_on_submit():
        b.name = form.name.data.strip()
        b.department_name = (form.department_name.data or None) or None
        b.order = int(form.order.data or 0)
        b.active = bool(form.active.data)
        try:
            sel = int(form.workflow_id.data or 0)
        except Exception:
            sel = 0
        b.workflow_id = sel or None
        db.session.commit()
        flash("Bucket updated.", "success")
        # handle bulk-add statuses if provided
        bulk = (form.bulk_statuses.data or "").strip()
        if bulk:
            lines = [l.strip() for l in bulk.splitlines() if l.strip()]
            if lines:
                # compute next order base
                existing = b.statuses.order_by(BucketStatus.order.desc()).first()
                base = existing.order + 1 if existing else 0
                for idx, code in enumerate(lines):
                    ns = BucketStatus(
                        bucket_id=b.id, status_code=code, order=base + idx
                    )
                    db.session.add(ns)
                db.session.commit()
                flash(f"Added {len(lines)} statuses to bucket.", "success")
        return redirect(url_for("admin.list_buckets"))

    # handle adding a new status code via POST param (supports select or free text)
    if flask_request.method == "POST" and (
        flask_request.form.get("new_status_code")
        or flask_request.form.get("new_status_code_select")
    ):
        code = (
            flask_request.form.get("new_status_code_select")
            or flask_request.form.get("new_status_code")
            or ""
        ).strip()
        try:
            ordv = int(flask_request.form.get("new_status_order") or 0)
        except Exception:
            ordv = 0
        if code:
            ns = BucketStatus(bucket_id=b.id, status_code=code, order=ordv)
            db.session.add(ns)
            db.session.commit()
            flash("Added status to bucket.", "success")
        return redirect(url_for("admin.buckets_edit", bucket_id=b.id))

    statuses = b.statuses.order_by(BucketStatus.order.asc()).all()

    # Load available status options and workflows scoped to this bucket's department
    if b.department_name:
        status_opts = (
            StatusOption.query.filter(
                (StatusOption.target_department == None)
                | (StatusOption.target_department == b.department_name)
            )
            .order_by(StatusOption.code.asc())
            .all()
        )
        workflows = (
            Workflow.query.filter(
                (Workflow.department_code == None)
                | (Workflow.department_code == b.department_name)
            )
            .filter(Workflow.active == True)
            .order_by(Workflow.name.asc())
            .all()
        )
    else:
        status_opts = StatusOption.query.order_by(StatusOption.code.asc()).all()
        workflows = (
            Workflow.query.filter(Workflow.active == True)
            .order_by(Workflow.name.asc())
            .all()
        )

    return render_template(
        "admin_bucket_form.html",
        form=form,
        bucket=b,
        statuses=statuses,
        status_options=status_opts,
        workflows=workflows,
    )


@admin_bp.route("/buckets/<int:bucket_id>/delete", methods=["POST"])
@login_required

def buckets_delete(bucket_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    b = get_or_404(StatusBucket, bucket_id)
    db.session.delete(b)
    db.session.commit()
    flash("Bucket deleted.", "success")
    return redirect(url_for("admin.list_buckets"))


@admin_bp.route(
    "/buckets/<int:bucket_id>/status/<int:status_id>/delete", methods=["POST"]
)
@login_required

def buckets_status_delete(bucket_id: int, status_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    s = get_or_404(BucketStatus, status_id)
    db.session.delete(s)
    db.session.commit()
    flash("Bucket status removed.", "success")
    return redirect(url_for("admin.buckets_edit", bucket_id=bucket_id))


@admin_bp.route("/buckets/<int:bucket_id>/reorder_statuses", methods=["POST"])
@login_required

def buckets_reorder_statuses(bucket_id: int):
    if not _is_admin_user():
        return jsonify({"error": "access_denied"}), 403

    b = get_or_404(StatusBucket, bucket_id)
    try:
        payload = flask_request.get_json(force=True)
    except Exception:
        payload = None
    if (
        not payload
        or "order" not in payload
        or not isinstance(payload.get("order"), list)
    ):
        return jsonify({"error": "invalid_payload"}), 400

    ids = [int(x) for x in payload.get("order") if str(x).isdigit()]
    # ensure all ids belong to this bucket
    items = {
        s.id: s
        for s in BucketStatus.query.filter(
            BucketStatus.bucket_id == b.id, BucketStatus.id.in_(ids)
        ).all()
    }
    # apply new order
    for idx, sid in enumerate(ids):
        s = items.get(sid)
        if s:
            s.order = int(idx)
            db.session.add(s)
    db.session.commit()
    return jsonify({"ok": True})