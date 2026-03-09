from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    current_app,
    session,
    jsonify,
)
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

from ..extensions import db, get_or_404
from ..models import User
from .forms import SiteConfigForm, DepartmentForm
from .forms import NotificationRetentionForm
from ..models import Request as ReqModel, Artifact, Submission, SiteConfig, Department
from ..models import StatusOption, DepartmentEditor
from ..models import IntegrationConfig
from ..models import Tenant, TenantMembership, JobRecord, IntegrationEvent
from datetime import datetime, timedelta
from flask import request as flask_request
from ..models import (
    Notification,
    AuditLog,
    NotificationRetention,
    StatusBucket,
    BucketStatus,
)
from ..models import FeatureFlags, RejectRequestConfig
from urllib.parse import unquote
import os
import json
from werkzeug.utils import secure_filename
from ..models import Workflow
from .forms import WorkflowForm
from .forms import StatusBucketForm
from .forms import FormTemplateAdminForm, FormFieldInlineForm
from .forms import DepartmentAssignmentForm
from ..models import FormTemplate, FormField, DepartmentFormAssignment
from .forms import FieldVerificationForm, FieldRequirementForm
from ..models import FieldVerification
from ..requests_bp.workflow import owner_for_status
from ..services.integrations import (
    INTEGRATION_KIND_SCAFFOLDS,
    get_integration_scaffold,
    integration_config_summary,
    normalize_integration_config,
)
from ..services.field_verification import apply_bulk_verification_params
from ..services.branding_importer import BrandingImportError, import_branding_from_url
from ..services.template_admin import (
    build_grouped_template_fields,
    build_requirement_editor_context,
    parse_requirement_rules_form,
    populate_requirement_form_from_rules,
    update_template_field_settings,
)
from ..services.tenant_context import get_current_tenant, tenant_role_for_user, user_has_permission, ensure_user_tenant_membership
from .utils import _is_admin_user

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _submitted_checkbox_enabled(field_name: str) -> bool:
    """Return the posted boolean state for a checkbox-like field.

    Admin toggle forms post the whole settings surface at once. When a box is
    unchecked the browser omits the field entirely, so relying on WTForms field
    defaults can accidentally flip omitted values back to their default `True`.
    Reading directly from the submitted form keeps checkbox behavior intuitive:
    present means enabled, absent means disabled.
    """

    raw = (flask_request.form.get(field_name) or "").strip().lower()
    return raw not in ("", "0", "false", "off", "no")

# Load auxiliary handlers to keep this file from growing even more.
# Load auxiliary handlers to keep this file from growing even more.
# ``tenants`` and ``users`` must be imported after ``admin_bp`` is defined so the
# routes they declare can attach to the same blueprint.
from . import tenants  # noqa: F401, E402
from . import users    # noqa: F401, E402
from . import workflows  # noqa: F401, E402
from . import guest_forms  # noqa: F401, E402


@admin_bp.route("/toggle_notifications", methods=["POST"])
@login_required

def toggle_notifications():
    """Flip the global notifications flag and return to dashboard."""
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    flags = FeatureFlags.get()
    flags.enable_notifications = not bool(flags.enable_notifications)
    db.session.commit()
    flash(f"Notifications {'enabled' if flags.enable_notifications else 'disabled'}.", "success")
    return redirect(url_for("admin.index"))

@admin_bp.route("/")
@login_required
def index():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    tenant = get_current_tenant()
    total_users = User.query.count()
    total_depts = Department.query.count()
    total_audit = AuditLog.query.count()
    total_jobs = JobRecord.query.count()
    total_events = IntegrationEvent.query.count()
    total_tenants = Tenant.query.count()
    # expose feature flags so dashboard tiles may reflect their state
    flags = FeatureFlags.get()
    return render_template(
        "admin_index.html",
        total_users=total_users,
        total_depts=total_depts,
        total_audit=total_audit,
        total_jobs=total_jobs,
        total_events=total_events,
        total_tenants=total_tenants,
        current_tenant_name=getattr(tenant, "name", "Default Workspace"),
        current_tenant_role=tenant_role_for_user(current_user),
        flags=flags,
    )


@admin_bp.route("/monitor")
@login_required
def monitor():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    dept = (flask_request.args.get("dept") or "B").upper()
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=24)

    # Gather admin-only metrics
    total_users = User.query.count()
    active_users = User.query.filter_by(is_active=True).count()
    admin_count = User.query.filter_by(is_admin=True).count()
    recent_email_issues = (
        Notification.query.filter(
            Notification.type.in_(["email_failed", "email_skipped"])
        )
        .order_by(Notification.created_at.desc())
        .limit(20)
        .all()
    )

    if dept == "A":
        reqs = (
            ReqModel.query.join(User, ReqModel.created_by_user_id == User.id)
            .filter(User.department == "A")
            .order_by(ReqModel.updated_at.desc())
            .all()
        )
        dashboard_html = render_template(
            "dashboard.html", mode="A", requests=reqs, now=now
        )
        return render_template(
            "admin_monitor.html",
            dept=dept,
            dashboard_html=dashboard_html,
            total_users=total_users,
            active_users=active_users,
            admin_count=admin_count,
            recent_email_issues=recent_email_issues,
        )

    if dept == "B":
        from ..utils.dept_scope import scope_requests_for_department

        base_b = scope_requests_for_department(ReqModel.query, "B")
        buckets = {
            "New from A": base_b.filter(ReqModel.status == "NEW_FROM_A")
            .order_by(ReqModel.updated_at.desc())
            .all(),
            "In progress by Department B": base_b.filter(
                ReqModel.status == "B_IN_PROGRESS"
            )
            .order_by(ReqModel.updated_at.desc())
            .all(),
            "Pending review from Department A": base_b.filter(
                ReqModel.status == "WAITING_ON_A_RESPONSE"
            )
            .order_by(ReqModel.updated_at.desc())
            .all(),
            "Needs changes": base_b.filter(ReqModel.status == "C_NEEDS_CHANGES")
            .order_by(ReqModel.updated_at.desc())
            .all(),
        }

        dashboard_html = render_template(
            "dashboard.html",
            mode="B",
            buckets=buckets,
            now=now,
        )
        return render_template(
            "admin_monitor.html",
            dept=dept,
            dashboard_html=dashboard_html,
            total_users=total_users,
            active_users=active_users,
            admin_count=admin_count,
            recent_email_issues=recent_email_issues,
        )

    if dept == "C":
        pending = (
            ReqModel.query.filter_by(status="PENDING_C_REVIEW")
            .order_by(ReqModel.updated_at.desc())
            .all()
        )
        dashboard_html = render_template(
            "dashboard.html", mode="C", requests=pending, now=now
        )
        return render_template(
            "admin_monitor.html",
            dept=dept,
            dashboard_html=dashboard_html,
            total_users=total_users,
            active_users=active_users,
            admin_count=admin_count,
            recent_email_issues=recent_email_issues,
        )

    flash("Unknown department", "warning")
    return redirect(url_for("admin.monitor", dept="B"))


@admin_bp.route("/jobs")
@login_required
def job_overview():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    jobs = JobRecord.query.order_by(JobRecord.created_at.desc()).limit(200).all()
    return render_template("admin_jobs.html", jobs=jobs)


@admin_bp.route("/integration_events")
@login_required
def integration_events():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    events = IntegrationEvent.query.order_by(IntegrationEvent.created_at.desc()).limit(200).all()
    summary = {
        "pending": IntegrationEvent.query.filter_by(status="pending").count(),
        "failed": IntegrationEvent.query.filter_by(status="failed").count(),
        "delivered": IntegrationEvent.query.filter_by(status="delivered").count(),
        "jobs_failed": JobRecord.query.filter_by(status="failed").count(),
        "jobs_running": JobRecord.query.filter(JobRecord.status.in_(["queued", "running"])).count(),
    }
    return render_template("admin_integration_events.html", events=events, summary=summary)


@admin_bp.route("/integration_events/<int:event_id>/retry", methods=["POST"])
@login_required
def retry_integration_event(event_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    event = get_or_404(IntegrationEvent, event_id)
    event.status = "pending"
    event.last_error = None
    event.delivered_at = None
    event.next_retry_at = datetime.utcnow()
    db.session.add(event)
    db.session.commit()
    flash(f"Integration event {event.id} queued for retry.", "success")
    return redirect(url_for("admin.integration_events"))


@admin_bp.route("/debug_workspace")
@login_required
def debug_workspace():
    # Small helper page that loads an internal path inside an iframe for debugging.
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    path = (
        flask_request.args.get("path") or flask_request.args.get("url") or "/dashboard"
    )
    try:
        path = unquote(path)
    except Exception:
        pass
    if not path.startswith("/"):
        path = "/dashboard"
    return render_template("admin_debug_workspace.html", path=path)


@admin_bp.route("/debug/cleanup", methods=["POST"])
@login_required
def debug_cleanup():
    # Admin-only maintenance endpoint to remove smoke or debug rows.
    if not _is_admin_user():
        return jsonify({"error": "access_denied"}), 403

    confirm = flask_request.args.get("confirm") or flask_request.form.get("confirm")
    if str(confirm).lower() != "true":
        return jsonify({"error": "missing_confirm", "note": "set confirm=true"}), 400

    try:
        days = int(flask_request.args.get("days") or 0)
    except Exception:
        days = 0

    if days > 0:
        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted = ReqModel.query.filter(
            ReqModel.is_debug == True, ReqModel.created_at < cutoff
        ).delete(synchronize_session=False)
    else:
        deleted = ReqModel.query.filter(ReqModel.title.like("SMOKE_%")).delete(
            synchronize_session=False
        )

    db.session.commit()
    return jsonify({"deleted": int(deleted)})


@admin_bp.route("/audit")
@login_required
def audit():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    q = flask_request.args.get("user")
    action = flask_request.args.get("action")
    audits = AuditLog.query.order_by(AuditLog.created_at.desc())
    if q:
        audits = audits.join(User, AuditLog.actor_user_id == User.id).filter(
            User.email.ilike(f"%{q}%")
        )
    if action:
        audits = audits.filter(AuditLog.action_type.ilike(f"%{action}%"))
    audits = audits.limit(200).all()
    return render_template("admin_audit.html", audits=audits)


@admin_bp.route("/site_config", methods=["GET", "POST"])
@login_required
def site_config():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    # `SiteConfig.get` has its own defensive error handling; prefer it here so
    # that a misconfigured or out‑of‑date database won't blow up the admin UI.
    try:
        cfg = SiteConfig.get()
    except Exception as exc:  # pragma: no cover - extremely rare but safe
        current_app.logger.exception("unable to load site config")
        flash(
            "Unable to load site configuration (database error). "
            "Please ensure migrations have been applied.",
            "danger",
        )
        # fall back to empty object so form rendering still works
        cfg = None
    else:
        # SiteConfig.get will return a fresh object if the query failed due to a
        # missing table/column.  That object will not have been committed and
        # therefore its primary key will still be ``None``.  This is worth
        # warning the admin about so they know something's wrong in the
        # database even though the page will render.
        if cfg is not None and getattr(cfg, "id", None) is None:
            flash(
                "Site configuration cannot be loaded from the database; "
                "your schema may be out of date.",
                "warning",
            )

    form = SiteConfigForm(obj=cfg)
    # regardless of request method, populate active_quote_set choices so that
    # validation succeeds on POST even when the admin is changing the value.  A
    # failing validation here previously caused "Not a valid choice" and made
    # the page render again without the success flash.
    try:
        keys = list((getattr(cfg, "rolling_quote_sets", {}) or {}).keys())
        if not keys:
            keys = list(cfg.rolling_quote_sets.keys()) if cfg else ['default']
        if 'default' not in keys:
            keys.insert(0, 'default')
        form.active_quote_set.choices = [(k, k.title()) for k in keys]
    except Exception:
        form.active_quote_set.choices = [('default', 'Default')]

    if flask_request.method == "GET" and cfg:
        form.import_url.data = getattr(cfg, "company_url", None)
        form.brand_name.data = getattr(cfg, "brand_name", None)
        form.company_url.data = getattr(cfg, "company_url", None)
        form.theme_preset.data = getattr(cfg, "theme_preset", "default") or "default"
        form.navbar_banner.data = getattr(cfg, "banner_html", None) or getattr(
            cfg, "navbar_banner", None
        )
        try:
            rq = getattr(cfg, "rolling_quotes", []) or []
            form.rolling_quotes.data = (
                "\n".join(rq) if isinstance(rq, list) else str(rq)
            )
        except Exception:
            form.rolling_quotes.data = None
        try:
            # expose named quote-sets to the admin UI (JSON map)
            sets = getattr(cfg, "rolling_quote_sets", {}) or {}
            form.rolling_quote_sets.data = json.dumps(sets, indent=2)
        except Exception:
            form.rolling_quote_sets.data = None
        # load permissions JSON if available
        try:
            cfg.company_url = form.company_url.data or None
        except Exception:
            pass
        try:
            perms = getattr(cfg, "quote_permissions", None)
            if perms:
                parsed = json.loads(perms)
                dept = parsed.get("departments")
                user = parsed.get("users")
                form.quote_permissions_dept.data = json.dumps(dept or {}, indent=2)
                form.quote_permissions_user.data = json.dumps(user or {}, indent=2)
        except Exception:
            form.quote_permissions_dept.data = None
            form.quote_permissions_user.data = None
        try:
            # populate choices for active set selector (also refresh data value)
            keys = list((getattr(cfg, "rolling_quote_sets", {}) or {}).keys())
            if not keys:
                keys = list(cfg.rolling_quote_sets.keys()) if cfg else ['default']
            if 'default' not in keys:
                keys.insert(0, 'default')
            form.active_quote_set.choices = [(k, k.title()) for k in keys]
            form.active_quote_set.data = getattr(cfg, 'active_quote_set', 'default')
        except Exception:
            form.active_quote_set.choices = [('default','Default')]
            form.active_quote_set.data = getattr(cfg, 'active_quote_set', 'default')
        form.show_banner.data = bool(
            getattr(cfg, "rolling_quotes_enabled", getattr(cfg, "show_banner", False))
        )

    if flask_request.method == "POST" and flask_request.form.get("import_branding"):
        if not cfg:
            cfg = SiteConfig()
            db.session.add(cfg)
        if not form.import_url.data:
            flash("Enter a website URL to import branding.", "warning")
        elif not form.import_url.validate(form):
            for err in form.import_url.errors:
                flash(err, "danger")
        else:
            try:
                imported = import_branding_from_url(
                    form.import_url.data,
                    static_folder=current_app.static_folder
                    or os.path.join(current_app.root_path, "static"),
                )
                if imported.brand_name:
                    cfg.brand_name = imported.brand_name
                cfg.company_url = imported.company_url
                if imported.theme_preset:
                    cfg.theme_preset = imported.theme_preset
                if imported.logo_filename:
                    cfg.logo_filename = imported.logo_filename
                db.session.commit()
                try:
                    entry = AuditLog(
                        actor_type="user",
                        actor_label=getattr(current_user, "email", "admin"),
                        action_type="site_config_import",
                        target_type="site_config",
                        target_id=str(getattr(cfg, "id", "")),
                        metadata_json=json.dumps(
                            {
                                "source_url": imported.source_url,
                                "brand_name": imported.brand_name,
                                "company_url": imported.company_url,
                                "theme_preset": imported.theme_preset,
                                "logo_imported": bool(imported.logo_filename),
                            }
                        ),
                    )
                    db.session.add(entry)
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                flash("Branding imported safely from the website.", "success")
                return redirect(url_for("admin.site_config"))
            except BrandingImportError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
            except Exception:
                db.session.rollback()
                current_app.logger.exception("branding import failed")
                flash("Branding import failed. The site configuration was not changed.", "danger")

    if form.validate_on_submit():
        if not cfg:
            cfg = SiteConfig()
            db.session.add(cfg)
        # Support both current field names and legacy payload keys used by tests/UI.
        banner = form.navbar_banner.data
        if not banner:
            banner = flask_request.form.get("banner_html")

        rolling_enabled = bool(form.show_banner.data)
        if "rolling_enabled" in flask_request.form:
            rolling_enabled = True

        # only consider updating rolling quotes if admin actually typed or
        # pasted something into the textarea (or provided the legacy CSV field).
        rolling_input = None
        if 'rolling_quotes' in flask_request.form or 'rolling_csv' in flask_request.form:
            rolling_input = form.rolling_quotes.data
            if not rolling_input:
                rolling_input = flask_request.form.get("rolling_csv")

        cfg.brand_name = (form.brand_name.data or "").strip() or None
        cfg.theme_preset = (form.theme_preset.data or "default").strip().lower()
        if cfg.theme_preset not in ("default", "ocean", "forest", "sunset", "midnight"):
            cfg.theme_preset = "default"

        remove_logo = bool(form.clear_logo.data)
        uploaded_logo = flask_request.files.get("logo_upload")
        if remove_logo:
            cfg.logo_filename = None
        if uploaded_logo and uploaded_logo.filename:
            filename = secure_filename(uploaded_logo.filename)
            if filename:
                ext = os.path.splitext(filename)[1].lower()
                stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
                stored_name = f"logo_{stamp}{ext}"
                rel_dir = os.path.join("uploads", "branding")
                static_dir = current_app.static_folder or os.path.join(
                    current_app.root_path, "static"
                )
                abs_dir = os.path.join(static_dir, rel_dir)
                os.makedirs(abs_dir, exist_ok=True)
                uploaded_logo.save(os.path.join(abs_dir, stored_name))
                cfg.logo_filename = f"uploads/branding/{stored_name}"

        cfg.banner_html = _sanitize_banner_html(banner) or None
        cfg.rolling_quotes_enabled = rolling_enabled
        if rolling_input is not None:
            # preserve existing quotes when no data submitted
            cfg.rolling_quotes = rolling_input or None
        # allow admins to set the default advance interval (seconds)
        if hasattr(form, 'rolling_quote_interval_default'):
            try:
                if 'rolling_quote_interval_default' in flask_request.form:
                    cfg.rolling_quote_interval_default = int(form.rolling_quote_interval_default.data or 0)
            except Exception:
                pass
        # save named quote sets if provided (expect JSON map string).  only
        # update the column when the field is actually included in the POST data
        # so that a simple change to another setting (e.g. active_quote_set) does
        # not inadvertently clear the existing sets.
        try:
            # only update when admin has actually provided non-empty JSON in the
            # textarea; blank submissions (common when changing other settings) should
            # not erase previously configured sets.
            if 'rolling_quote_sets' in flask_request.form:
                raw = form.rolling_quote_sets.data or flask_request.form.get('rolling_quote_sets')
                if raw and raw.strip():
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        cfg._rolling_quote_sets = json.dumps(SiteConfig.normalize_quote_sets(parsed))
                    else:
                        cfg._rolling_quote_sets = None
                # else: leave existing value alone
        except Exception:
            # ignore invalid JSON, sanitize on next GET
            pass
        try:
            cfg.active_quote_set = form.active_quote_set.data or 'default'
        except Exception:
            cfg.active_quote_set = 'default'
        # handle quote permissions
        try:
            perms = {"departments": {}, "users": {}}
            raw_dept = form.quote_permissions_dept.data or flask_request.form.get('quote_permissions_dept')
            raw_user = form.quote_permissions_user.data or flask_request.form.get('quote_permissions_user')
            if raw_dept:
                imported = json.loads(raw_dept)
                if isinstance(imported, dict):
                    perms['departments'] = imported
            if raw_user:
                imported = json.loads(raw_user)
                if isinstance(imported, dict):
                    perms['users'] = imported
            cfg.quote_permissions = json.dumps(perms)
        except Exception:
            # ignore invalid JSON, sanitize on next GET
            pass
        try:
            db.session.commit()
            flash("Site configuration saved.", "success")
            # record audit entry so changes are traceable
            try:
                from app.models import AuditLog
                entry = AuditLog(
                    actor_type="user",
                    actor_user_id=current_user.id,
                    actor_label=current_user.email,
                    action_type="site_config_update",
                    note="admin updated site configuration",
                )
                db.session.add(entry)
                db.session.commit()
            except Exception:
                current_app.logger.exception(
                    "failed to audit site config change"
                )
        except Exception as exc:  # pragma: no cover - defensive
            current_app.logger.exception("failed to save site config")
            try:
                db.session.rollback()
            except Exception:
                pass
            flash(
                "Failed to save site configuration (database error).", "danger"
            )
        return redirect(url_for("admin.site_config"))

    if flask_request.method == "POST" and form.errors:
        for field_errors in form.errors.values():
            for error in field_errors:
                flash(error, "danger")

    return render_template("admin_site_config.html", form=form, cfg=cfg)


@admin_bp.route("/quotes", methods=["GET"])
@login_required
def quotes_config():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    return redirect(url_for("admin.site_config", _anchor="quotes-settings"))


@admin_bp.route("/site_config/preview", methods=["POST"])
@login_required
def site_config_preview():
    if not _is_admin_user():
        return jsonify({"error": "access_denied"}), 403

    # Accept multipart form or JSON payload
    raw_sets = None
    raw_quotes = None
    try:
        raw_sets = flask_request.form.get("rolling_quote_sets") or flask_request.json and flask_request.json.get("rolling_quote_sets")
        raw_quotes = flask_request.form.get("rolling_csv") or flask_request.form.get("rolling_quotes") or (flask_request.json and flask_request.json.get("rolling_quotes"))
    except Exception:
        raw_sets = None
        raw_quotes = None

    active = flask_request.form.get("active_quote_set") or (flask_request.json and flask_request.json.get("active_quote_set")) or "default"

    try:
        parsed = json.loads(raw_sets) if raw_sets else {}
    except Exception:
        return jsonify({"error": "invalid_json", "message": "Could not parse rolling_quote_sets as JSON."}), 400

    if not isinstance(parsed, dict):
        return jsonify({"error": "invalid_type", "message": "rolling_quote_sets must be a JSON object."}), 400

    if raw_quotes:
        parsed.setdefault(
            "default",
            [line.strip() for line in str(raw_quotes).splitlines() if line.strip()],
        )

    parsed = SiteConfig.normalize_quote_sets(parsed)

    active_list = parsed.get(active) or parsed.get(str(active)) or []
    if not isinstance(active_list, list):
        return jsonify({"error": "invalid_set", "message": "Active set is not a list."}), 400

    sample = [s for s in active_list if isinstance(s, str)][:20]
    return jsonify({"active": active, "count": len(active_list), "sample": sample})


def _sanitize_banner_html(raw: str) -> str:
    """Sanitize admin-provided banner HTML for safe display.

    This function performs light cleaning to remove markdown code fences
    (```...```) and stray triple-backticks that sometimes get pasted into
    the banner content. We deliberately avoid heavy HTML sanitization here
    because banner content is expected to be HTML; this helper focuses on
    removing accidental code fences and obvious artifacts that break the
    navbar rendering.
    """
    if not raw:
        return raw

    # first remove accidental fenced-code artifacts which often break the
    # navbar rendering (e.g. ```...```) so we strip those explicitly.
    import re

    s = str(raw or "")
    s = re.sub(r"```[\s\S]*?```", "", s)
    s = s.replace('```', '')

    # Use bleach to perform a conservative HTML sanitization: allow a small
    # set of formatting tags and safe attributes, strip anything else (including
    # <script> tags and event handlers). We avoid allowing inline CSS here to
    # keep banner rendering predictable.
    try:
        import bleach

        allowed_tags = [
            "a",
            "b",
            "strong",
            "i",
            "em",
            "u",
            "p",
            "br",
            "span",
            "div",
            "ul",
            "ol",
            "li",
            "img",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "small",
            "blockquote",
            "pre",
            "code",
            "hr",
        ]

        allowed_attrs = {
            "a": ["href", "title", "target", "rel"],
            "img": ["src", "alt", "title", "width", "height"],
            "*": ["id", "class", "role", "aria-hidden"],
        }

        # Tight CSS whitelist: only permit a short, safe set of CSS properties
        # for inline `style` usage. This prevents arbitrary CSS from affecting
        # layout or injecting harmful rules.
        try:
            from bleach.css_sanitizer import CSSSanitizer

            css_whitelist = [
                "color",
                "background-color",
                "text-align",
                "font-weight",
                "font-style",
                "text-decoration",
                "vertical-align",
            ]
            css_sanitizer = CSSSanitizer(allowed_css_properties=css_whitelist)
            allowed_attrs["*"] = allowed_attrs["*"] + ["style"]
        except Exception:
            css_sanitizer = None

        cleaned = bleach.clean(
            s,
            tags=allowed_tags,
            attributes=allowed_attrs,
            protocols=["http", "https", "mailto"],
            strip=True,
            css_sanitizer=css_sanitizer,
        )
        # Remove navigation/file targets that point at static assets so banner
        # markup cannot hijack button clicks or navigate users to JS/CSS files.
        cleaned = re.sub(
            r'\s(?:href|src|action|formaction)=(["\'])/static/[^"\']*\1',
            '',
            cleaned,
            flags=re.IGNORECASE,
        )
        # Trim and return
        return (cleaned or "").strip()
    except Exception:
        # If bleach isn't available for some reason, fall back to a minimal
        # regex-based cleanup.  We still want to remove dangerous tags and
        # static asset targets even if the full sanitizer fails.
        import re

        # strip script blocks
        s2 = re.sub(r'<script[\s\S]*?</script>', '', s, flags=re.IGNORECASE)
        # remove links/forms pointing at /static/ resources
        s2 = re.sub(
            r'\s(?:href|src|action|formaction)=(["\"])\/static\/[^"\']*\1',
            '',
            s2,
            flags=re.IGNORECASE,
        )
        return (s2 or "").strip()


@admin_bp.route('/site_config/clean_banner', methods=['POST'])
@login_required
def clean_banner():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    cfg = SiteConfig.query.first()
    if not cfg or not getattr(cfg, 'banner_html', None):
        flash('No banner content found to clean.', 'info')
        return redirect(url_for('admin.site_config'))

    cleaned = _sanitize_banner_html(cfg.banner_html or '')
    if cleaned == (cfg.banner_html or ''):
        flash('Banner content appears clean (no changes made).', 'info')
        return redirect(url_for('admin.site_config'))

    try:
        cfg.banner_html = cleaned or None
        db.session.commit()
        flash('Banner content cleaned successfully.', 'success')
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        flash('Failed to save cleaned banner content.', 'danger')

    return redirect(url_for('admin.site_config'))


@admin_bp.route('/site_config/preview_banner', methods=['POST'])
@login_required
def preview_banner():
    """Return a JSON preview of original vs cleaned banner HTML.

    This endpoint allows the admin UI to show a side-by-side preview before
    committing changes.
    """
    if not _is_admin_user():
        return jsonify({'error': 'access_denied'}), 403

    raw = flask_request.form.get('banner') or flask_request.form.get('navbar_banner') or ''
    cleaned = _sanitize_banner_html(raw)
    return jsonify({'original': raw, 'cleaned': cleaned})


@admin_bp.route("/unmapped-submissions")
@login_required
def unmapped_submissions():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    # Load recent submissions and filter for those without an automated mapping
    subs = Submission.query.order_by(Submission.created_at.desc()).limit(200).all()
    unmapped = []
    for s in subs:
        data = getattr(s, "data", None) or {}
        if not (isinstance(data, dict) and data.get("_mapped")):
            unmapped.append(s)

    return render_template("admin_unmapped_submissions.html", submissions=unmapped)


@admin_bp.route(
    "/unmapped-submissions/<int:submission_id>/map", methods=["GET", "POST"]
)
@login_required
def map_submission(submission_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    s = get_or_404(Submission, submission_id)
    data = getattr(s, "data", {}) or {}
    # present only payload keys that look like user fields (skip internal metadata)
    payload_keys = [
        k
        for k in (list(data.keys()) if isinstance(data, dict) else [])
        if not str(k).startswith("_")
    ]

    # Fields available in the template (if any)
    template = None
    fields = []
    try:
        if s.template_id:
            template = FormTemplate.query.get(s.template_id)
        if template:
            fields = sorted(
                getattr(template, "fields", []) or [], key=lambda f: f.label
            )
    except Exception:
        current_app.logger.exception("Failed loading template/fields for mapping UI")

    if flask_request.method == "POST":
        # Expect form keys map__<payload_key> -> field_id or empty
        mapping = {}
        for pk in payload_keys:
            form_key = f"map__{pk}"
            val = flask_request.form.get(form_key)
            if val:
                try:
                    fid = int(val)
                    mapping[pk] = fid
                except Exception:
                    continue

        # Persist mapping into the submission.data under reserved keys
        try:
            newdata = dict(data or {})
            field_map = {}
            for pk, fid in mapping.items():
                # capture the value and the mapped field id
                field_map[str(fid)] = {"payload_key": pk, "value": newdata.get(pk)}
            if field_map:
                newdata["_field_map"] = field_map
                newdata["_mapped"] = True
                s.data = newdata
                db.session.commit()
                flash("Saved mapping for submission.", "success")
                return redirect(url_for("admin.unmapped_submissions"))
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            current_app.logger.exception("Failed saving mapping for submission")
            flash("Failed saving mapping.", "danger")

    return render_template(
        "admin_map_submission.html",
        submission=s,
        payload_keys=payload_keys,
        fields=fields,
    )


@admin_bp.route("/templates")
@login_required
def list_templates():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    templates = FormTemplate.query.order_by(FormTemplate.created_at.desc()).all()
    return render_template("admin_templates.html", templates=templates)


@admin_bp.route("/templates/new", methods=["GET", "POST"])
@login_required
def create_template():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    form = FormTemplateAdminForm()
    if form.validate_on_submit():
        t = FormTemplate(
            name=form.name.data.strip(),
            description=(form.description.data or "").strip() or None,
            verification_prefill_enabled=bool(
                getattr(form, "verification_prefill_enabled", None)
                and form.verification_prefill_enabled.data
            ),
            layout=(getattr(form, "layout", None) and form.layout.data) or "standard",
            external_enabled=bool(
                getattr(form, "external_enabled", None) and form.external_enabled.data
            ),
            external_provider=(
                getattr(form, "external_provider", None)
                and (form.external_provider.data or "").strip()
            )
            or None,
            external_form_url=(
                getattr(form, "external_form_url", None)
                and (form.external_form_url.data or "").strip()
            )
            or None,
            external_form_id=(
                getattr(form, "external_form_id", None)
                and (form.external_form_id.data or "").strip()
            )
            or None,
        )
        db.session.add(t)
        db.session.commit()
        # create requested number of empty fields
        try:
            n = int(form.field_count.data or 0)
        except Exception:
            n = 0
        for i in range(max(0, n)):
            f = FormField(
                template_id=t.id,
                name=f"field_{i+1}",
                label=f"Field {i+1}",
                field_type="text",
                required=False,
            )
            db.session.add(f)
        db.session.commit()
        flash("Template created. Edit fields as needed.", "success")
        return redirect(url_for("admin.edit_template_fields", template_id=t.id))
    return render_template("admin_template_form.html", form=form)


@admin_bp.route("/templates/<int:template_id>/fields", methods=["GET", "POST"])
@login_required
def edit_template_fields(template_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    t = get_or_404(FormTemplate, template_id)
    # Handle simple bulk update: inputs named field_<id>_label, field_<id>_required
    if flask_request.method == "POST":
        update_template_field_settings(t, flask_request.form, db.session)
        db.session.commit()
        flash("Fields updated.", "success")
        return redirect(url_for("admin.list_templates"))

    # Render editing UI
    fields = sorted(
        list(t.fields), key=lambda ff: getattr(ff, "created_at", getattr(ff, "id", 0))
    )
    grouped_fields = build_grouped_template_fields(fields)
    return render_template(
        "admin_edit_template_fields.html",
        template=t,
        fields=fields,
        grouped_fields=grouped_fields,
    )


@admin_bp.route("/fields/<int:field_id>/verification", methods=["GET", "POST"])
@login_required
def edit_field_verification(field_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    f = get_or_404(FormField, field_id)
    # pick latest mapping if multiple
    fv = (
        FieldVerification.query.filter_by(field_id=f.id)
        .order_by(FieldVerification.created_at.desc())
        .first()
    )
    form = FieldVerificationForm()
    if flask_request.method == "GET" and fv:
        form.provider.data = fv.provider
        form.external_key.data = fv.external_key
        import json

        try:
            form.params_json.data = (
                json.dumps(fv.params, indent=2) if fv.params is not None else ""
            )
        except Exception:
            form.params_json.data = str(fv.params or "")
        try:
            form.triggers_auto_reject.data = bool(
                getattr(fv, "triggers_auto_reject", False)
            )
        except Exception:
            form.triggers_auto_reject.data = False
        try:
            params = fv.params if isinstance(fv.params, dict) else {}
        except Exception:
            params = {}
        form.verify_each_separated_value.data = bool(
            params.get("verify_each_separated_value", False)
        )
        form.value_separator.data = str(
            params.get("value_separator") or params.get("separator") or ","
        )
        form.bulk_input_hint.data = (
            params.get("bulk_input_hint") or params.get("entry_hint") or ""
        )
        form.prefill_enabled.data = bool(params.get("prefill_enabled", False))
        try:
            form.prefill_targets_json.data = json.dumps(
                params.get("prefill_targets") or {}, indent=2
            )
        except Exception:
            form.prefill_targets_json.data = ""
        form.prefill_overwrite_existing.data = bool(
            params.get("prefill_overwrite_existing", False)
        )

    if form.validate_on_submit():
        import json

        params = {}
        if form.params_json.data:
            try:
                params = json.loads(form.params_json.data)
            except Exception:
                flash("Invalid JSON in params field.", "danger")
                return render_template(
                    "admin_field_verification.html", form=form, field=f, fv=fv
                )
            if not isinstance(params, dict):
                flash("Params JSON must be a JSON object.", "danger")
                return render_template(
                    "admin_field_verification.html", form=form, field=f, fv=fv
                )

        params = apply_bulk_verification_params(
            params,
            verify_each_separated_value=bool(form.verify_each_separated_value.data),
            value_separator=form.value_separator.data,
            bulk_input_hint=form.bulk_input_hint.data,
        )

        if form.prefill_enabled.data:
            raw_prefill_targets = (form.prefill_targets_json.data or "").strip()
            prefill_targets = {}
            if raw_prefill_targets:
                try:
                    prefill_targets = json.loads(raw_prefill_targets)
                except Exception:
                    flash("Invalid JSON in prefill targets field.", "danger")
                    return render_template(
                        "admin_field_verification.html", form=form, field=f, fv=fv
                    )
                if not isinstance(prefill_targets, dict):
                    flash("Prefill targets JSON must be a JSON object.", "danger")
                    return render_template(
                        "admin_field_verification.html", form=form, field=f, fv=fv
                    )
            params["prefill_enabled"] = True
            params["prefill_targets"] = prefill_targets
            params["prefill_overwrite_existing"] = bool(
                form.prefill_overwrite_existing.data
            )
        else:
            params.pop("prefill_enabled", None)
            params.pop("prefill_targets", None)
            params.pop("prefill_overwrite_existing", None)

        # Replace existing mapping (simple policy: create new row)
        new = FieldVerification(
            field_id=f.id,
            provider=form.provider.data,
            external_key=(form.external_key.data or None),
            params=params,
            triggers_auto_reject=bool(form.triggers_auto_reject.data),
        )
        db.session.add(new)
        db.session.commit()
        flash("Field verification mapping saved.", "success")
        return redirect(
            url_for("admin.edit_template_fields", template_id=f.template_id)
        )

    return render_template("admin_field_verification.html", form=form, field=f, fv=fv)


@admin_bp.route("/fields/<int:field_id>/requirements", methods=["GET", "POST"])
@login_required
def edit_field_requirements(field_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    f = get_or_404(FormField, field_id)
    editor_context = build_requirement_editor_context(f)

    form = FieldRequirementForm()
    current_rules = getattr(f, "requirement_rules", None) or {}

    if flask_request.method == "GET" and isinstance(current_rules, dict):
        populate_requirement_form_from_rules(form, current_rules)

    if form.validate_on_submit():
        if form.enabled.data:
            try:
                rule_config = parse_requirement_rules_form(form)
            except json.JSONDecodeError:
                flash("Invalid JSON in rules field.", "danger")
                return render_template(
                    "admin_field_requirements.html",
                    form=form,
                    field=f,
                    **editor_context,
                )
            except ValueError as exc:
                flash(str(exc), "danger")
                return render_template(
                    "admin_field_requirements.html",
                    form=form,
                    field=f,
                    **editor_context,
                )
        else:
            rule_config = None
        f.requirement_rules = rule_config
        db.session.add(f)
        db.session.commit()
        flash("Conditional requirement rules saved.", "success")
        return redirect(url_for("admin.edit_template_fields", template_id=f.template_id))

    return render_template(
        "admin_field_requirements.html",
        form=form,
        field=f,
        **editor_context,
    )


@admin_bp.route("/notifications_retention", methods=["GET", "POST"])
@login_required
def notifications_retention():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    cfg = NotificationRetention.get()
    form = NotificationRetentionForm()
    if flask_request.method == "GET":
        # prefill form
        form.retain_until_eod.data = bool(getattr(cfg, "retain_until_eod", True))
        if cfg and cfg.clear_after_read_seconds is not None:
            secs = int(cfg.clear_after_read_seconds)
            if secs == 0:
                form.clear_after_choice.data = "immediate"
            elif secs == 300:
                form.clear_after_choice.data = "5m"
            elif secs == 1800:
                form.clear_after_choice.data = "30m"
            elif secs == 3600:
                form.clear_after_choice.data = "1h"
            elif secs == 86400:
                form.clear_after_choice.data = "24h"
            else:
                days = max(1, min(7, int(secs / 86400)))
                form.clear_after_choice.data = "custom"
                form.custom_days.data = days
        else:
            form.clear_after_choice.data = "eod"
        form.max_notifications_per_user.data = int(
            getattr(cfg, "max_notifications_per_user", 20) or 20
        )

    if form.validate_on_submit():
        if not cfg:
            cfg = NotificationRetention()
            db.session.add(cfg)

        cfg.retain_until_eod = bool(form.retain_until_eod.data)
        choice = form.clear_after_choice.data
        if choice == "eod":
            cfg.clear_after_read_seconds = None
        elif choice == "immediate":
            cfg.clear_after_read_seconds = 0
        elif choice == "5m":
            cfg.clear_after_read_seconds = 300
        elif choice == "30m":
            cfg.clear_after_read_seconds = 1800
        elif choice == "1h":
            cfg.clear_after_read_seconds = 3600
        elif choice == "24h":
            cfg.clear_after_read_seconds = 86400
        elif choice == "custom":
            days = int(form.custom_days.data or 1)
            if days < 1:
                days = 1
            if days > 7:
                days = 7
            cfg.clear_after_read_seconds = days * 86400
            cfg.retain_until_eod = False

        maxn = int(form.max_notifications_per_user.data or 20)
        if maxn < 1:
            maxn = 1
        if maxn > 20:
            maxn = 20
        cfg.max_notifications_per_user = maxn
        cfg.max_retention_days = 7

        db.session.commit()
        flash("Notification retention updated.", "success")
        return redirect(url_for("admin.notifications_retention"))

    return render_template("admin_notifications_retention.html", form=form, cfg=cfg)


@admin_bp.route("/special_email", methods=["GET", "POST"])
@login_required
def special_email():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    from .forms import SpecialEmailConfigForm

    cfg = None
    try:
        from ..models import SpecialEmailConfig

        cfg = SpecialEmailConfig.get()
    except Exception:
        cfg = None

    form = SpecialEmailConfigForm()
    # Defensive: previous DB errors can leave the session in an aborted state
    # which causes subsequent queries to fail with InFailedSqlTransaction.
    try:
        db.session.rollback()
    except Exception:
        pass

    try:
        sso_users = (
            User.query.filter(User.sso_sub.isnot(None)).order_by(User.email.asc()).all()
        )
    except Exception:
        current_app.logger.exception(
            "Failed querying SSO users for special_email admin page"
        )
        try:
            db.session.rollback()
        except Exception:
            pass
        sso_users = []

    form.request_form_user_id.choices = [(0, "-- None --")] + [
        (u.id, f"{u.email} (Dept {u.department})") for u in sso_users
    ]
    if flask_request.method == "GET" and cfg:
        form.enabled.data = bool(getattr(cfg, "enabled", False))
        form.request_form_email.data = getattr(cfg, "request_form_email", None)
        form.request_form_user_id.data = int(
            getattr(cfg, "request_form_user_id", 0) or 0
        )
        form.request_form_first_message.data = getattr(
            cfg, "request_form_first_message", None
        )
        form.request_form_department.data = (
            getattr(cfg, "request_form_department", "A") or "A"
        )
        form.request_form_field_validation_enabled.data = bool(
            getattr(cfg, "request_form_field_validation_enabled", False)
        )
        form.request_form_auto_reject_oos_enabled.data = bool(
            getattr(cfg, "request_form_auto_reject_oos_enabled", False)
        )
        form.request_form_inventory_out_of_stock_notify_enabled.data = bool(
            getattr(cfg, "request_form_inventory_out_of_stock_notify_enabled", False)
        )
        form.request_form_inventory_out_of_stock_notify_mode.data = (
            getattr(cfg, "request_form_inventory_out_of_stock_notify_mode", "email")
            or "email"
        )
        form.request_form_inventory_out_of_stock_message.data = getattr(
            cfg, "request_form_inventory_out_of_stock_message", None
        )
        form.nudge_enabled.data = bool(getattr(cfg, "nudge_enabled", False))
        # convert stored float to string for the select field
        form.nudge_interval_hours.data = str(
            float(getattr(cfg, "nudge_interval_hours", 24) or 24)
        )
        form.nudge_min_delay_hours.data = int(
            getattr(cfg, "nudge_min_delay_hours", 4) or 4
        )

    if form.validate_on_submit():
        if not cfg:
            from ..models import SpecialEmailConfig

            cfg = SpecialEmailConfig()
            db.session.add(cfg)

        cfg.enabled = bool(form.enabled.data)
        selected_owner_id = int(form.request_form_user_id.data or 0)
        selected_owner = (
            db.session.get(User, selected_owner_id) if selected_owner_id else None
        )
        if selected_owner and not selected_owner.sso_sub:
            selected_owner = None
            selected_owner_id = 0

        cfg.request_form_user_id = selected_owner_id or None
        manual_inbox = (form.request_form_email.data or "").strip() or None
        cfg.request_form_email = manual_inbox or (
            selected_owner.email if selected_owner else None
        )
        cfg.request_form_first_message = (
            form.request_form_first_message.data or ""
        ).strip() or None
        cfg.request_form_department = (
            (form.request_form_department.data or "A").strip().upper()
        )
        if selected_owner:
            cfg.request_form_department = (
                (selected_owner.department or cfg.request_form_department or "A")
                .strip()
                .upper()
            )
        if cfg.request_form_department not in ("A", "B", "C"):
            cfg.request_form_department = "A"
        cfg.request_form_field_validation_enabled = bool(
            form.request_form_field_validation_enabled.data
        )
        cfg.request_form_auto_reject_oos_enabled = bool(
            form.request_form_auto_reject_oos_enabled.data
        )
        cfg.request_form_inventory_out_of_stock_notify_enabled = bool(
            form.request_form_inventory_out_of_stock_notify_enabled.data
        )
        cfg.request_form_inventory_out_of_stock_notify_mode = (
            (form.request_form_inventory_out_of_stock_notify_mode.data or "email")
            .strip()
            .lower()
        )
        if cfg.request_form_inventory_out_of_stock_notify_mode not in (
            "notification",
            "email",
            "both",
        ):
            cfg.request_form_inventory_out_of_stock_notify_mode = "email"
        cfg.request_form_inventory_out_of_stock_message = (
            form.request_form_inventory_out_of_stock_message.data or ""
        ).strip() or None

        cfg.nudge_enabled = bool(form.nudge_enabled.data)
        # store value as float; the form supplies a string from the select
        try:
            cfg.nudge_interval_hours = float(form.nudge_interval_hours.data or 24)
        except Exception:
            cfg.nudge_interval_hours = 24.0
        # enforce minimum allowed (4 hours); admin may only extend beyond this
        try:
            requested = int(form.nudge_min_delay_hours.data or 4)
        except Exception:
            requested = 4
        if requested < 4:
            requested = 4
            flash(
                "Minimum reminder delay cannot be less than 4 hours; adjusted to 4.",
                "warning",
            )
        cfg.nudge_min_delay_hours = requested

        db.session.commit()
        flash("Reminder / special email settings saved.", "success")
        return redirect(url_for("admin.special_email"))

    return render_template("admin_special_email.html", form=form, cfg=cfg)


@admin_bp.route("/email_routing")
@login_required
def email_routing_list():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    from ..models import EmailRouting

    rows = EmailRouting.query.order_by(EmailRouting.recipient_email.asc()).all()
    return render_template("admin_email_routing.html", rows=rows)


@admin_bp.route("/email_routing/new", methods=["GET", "POST"])
@login_required
def email_routing_new():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    from .forms import EmailRoutingForm

    form = EmailRoutingForm()
    if form.validate_on_submit():
        from ..models import EmailRouting

        r = EmailRouting(
            recipient_email=form.recipient_email.data.strip().lower(),
            department_code=form.department_code.data.strip().upper(),
        )
        db.session.add(r)
        db.session.commit()
        flash("Email routing mapping created.", "success")
        return redirect(url_for("admin.email_routing_list"))
    return render_template("admin_email_routing_form.html", form=form)


@admin_bp.route("/assignments")
@login_required
def list_assignments():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    rows = DepartmentFormAssignment.query.order_by(
        DepartmentFormAssignment.department_name.asc()
    ).all()
    # load templates map for display
    templates = {
        t.id: t for t in FormTemplate.query.order_by(FormTemplate.name.asc()).all()
    }
    return render_template("admin_assignments.html", rows=rows, templates=templates)


@admin_bp.route("/webhooks")
@login_required
def list_webhooks():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    # Show recent external submissions (those with a template_id)
    rows = (
        Submission.query.filter(Submission.template_id.isnot(None))
        .order_by(Submission.created_at.desc())
        .limit(200)
        .all()
    )
    templates = {
        t.id: t for t in FormTemplate.query.order_by(FormTemplate.name.asc()).all()
    }
    return render_template("admin_webhooks.html", rows=rows, templates=templates)


@admin_bp.route("/assignments/new", methods=["GET", "POST"])
@login_required
def new_assignment():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    form = DepartmentAssignmentForm()
    form.template_id.choices = [
        (t.id, t.name)
        for t in FormTemplate.query.order_by(FormTemplate.name.asc()).all()
    ]
    if form.validate_on_submit():
        # ensure one assignment per department (replace existing)
        DepartmentFormAssignment.query.filter_by(
            department_name=form.department.data
        ).delete()
        a = DepartmentFormAssignment(
            template_id=form.template_id.data, department_name=form.department.data
        )
        db.session.add(a)
        db.session.commit()
        flash("Template assigned to department.", "success")
        return redirect(url_for("admin.list_assignments"))

    return render_template("admin_assignments.html", form=form, rows=[], templates={})


@admin_bp.route("/assignments/<int:assignment_id>/delete", methods=["POST"])
@login_required
def delete_assignment(assignment_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    a = get_or_404(DepartmentFormAssignment, assignment_id)
    db.session.delete(a)
    db.session.commit()
    flash("Assignment removed.", "success")
    return redirect(url_for("admin.list_assignments"))


@admin_bp.route("/email_routing/<int:rid>/edit", methods=["GET", "POST"])
@login_required
def email_routing_edit(rid: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    from ..models import EmailRouting

    r = get_or_404(EmailRouting, rid)
    from .forms import EmailRoutingForm

    form = EmailRoutingForm(obj=r)
    if form.validate_on_submit():
        r.recipient_email = form.recipient_email.data.strip().lower()
        r.department_code = form.department_code.data.strip().upper()
        db.session.commit()
        flash("Email routing mapping updated.", "success")
        return redirect(url_for("admin.email_routing_list"))
    return render_template("admin_email_routing_form.html", form=form, edit=r)


@admin_bp.route("/email_routing/<int:rid>/delete", methods=["POST"])
@login_required
def email_routing_delete(rid: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    from ..models import EmailRouting

    r = get_or_404(EmailRouting, rid)
    db.session.delete(r)
    db.session.commit()
    flash("Email routing mapping deleted.", "success")
    return redirect(url_for("admin.email_routing_list"))


@admin_bp.route("/feature_flags", methods=["GET", "POST"])
@login_required
def feature_flags():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    from .forms import FeatureFlagsForm

    # Ensure any prior aborted DB transaction is cleared before reading flags.
    try:
        db.session.rollback()
    except Exception:
        pass
    try:
        flags = FeatureFlags.get()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        flags = FeatureFlags()
    form = FeatureFlagsForm()

    # support JSON autosave calls in addition to regular form POST
    if flask_request.is_json:
        data = flask_request.get_json(silent=True) or {}
        # update only the flags provided in the payload
        for field in (
            "enable_notifications",
            "enable_nudges",
            "allow_user_nudges",
            "vibe_enabled",
            "sso_admin_sync_enabled",
            "sso_department_sync_enabled",
            "enable_external_forms",
            "rolling_quotes_enabled",
        ):
            if field in data:
                try:
                    setattr(flags, field, bool(data[field]))
                except Exception:
                    pass
        try:
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            return jsonify({"ok": False, "error": "save_failed"}), 500
        # echo back current state
        return jsonify({
            "ok": True,
            "flags": {f: bool(getattr(flags, f, False)) for f in (
                "enable_notifications",
                "enable_nudges",
                "allow_user_nudges",
                "vibe_enabled",
                "sso_admin_sync_enabled",
                "sso_department_sync_enabled",
                "enable_external_forms",
                "rolling_quotes_enabled",
            )},
        })

    if flask_request.method == "GET":
        form.enable_notifications.data = bool(
            getattr(flags, "enable_notifications", True)
        )
        form.enable_nudges.data = bool(getattr(flags, "enable_nudges", True))
        form.allow_user_nudges.data = bool(getattr(flags, "allow_user_nudges", False))
        form.vibe_enabled.data = bool(getattr(flags, "vibe_enabled", True))
        form.sso_admin_sync_enabled.data = bool(
            getattr(flags, "sso_admin_sync_enabled", True)
        )
        form.sso_department_sync_enabled.data = bool(
            getattr(
                flags,
                "sso_department_sync_enabled",
                current_app.config.get("SSO_DEPARTMENT_SYNC_ENABLED", False),
            )
        )
        form.enable_external_forms.data = bool(
            getattr(flags, "enable_external_forms", False)
        )
        form.rolling_quotes_enabled.data = bool(
            getattr(flags, "rolling_quotes_enabled", True)
        )

    if form.validate_on_submit():
        flags.enable_notifications = _submitted_checkbox_enabled(
            "enable_notifications"
        )
        flags.enable_nudges = _submitted_checkbox_enabled("enable_nudges")
        flags.allow_user_nudges = _submitted_checkbox_enabled(
            "allow_user_nudges"
        )
        flags.vibe_enabled = _submitted_checkbox_enabled("vibe_enabled")
        flags.sso_admin_sync_enabled = _submitted_checkbox_enabled(
            "sso_admin_sync_enabled"
        )
        flags.sso_department_sync_enabled = _submitted_checkbox_enabled(
            "sso_department_sync_enabled"
        )
        flags.enable_external_forms = _submitted_checkbox_enabled(
            "enable_external_forms"
        )
        flags.rolling_quotes_enabled = _submitted_checkbox_enabled(
            "rolling_quotes_enabled"
        )
        db.session.commit()
        flash("Feature flags updated.", "success")
        return redirect(url_for("admin.feature_flags"))

    return render_template("admin_feature_flags.html", form=form, flags=flags)


@admin_bp.route("/metrics_config", methods=["GET", "POST"])
@login_required
def metrics_config():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    from .forms import MetricsConfigForm
    from ..models import MetricsConfig
    from ..services.process_metrics import build_process_metrics_summary

    def build_admin_metrics_explorer_context():
        allowed_depts = ["A", "B", "C"]
        range_key = (flask_request.args.get("range") or "weekly").lower()
        selected_dept = (flask_request.args.get("dept") or "").strip().upper()
        visible_depts = [selected_dept] if selected_dept in allowed_depts else allowed_depts
        query = (flask_request.args.get("q") or "").strip()
        user_filters = flask_request.args.getlist("user")

        snapshot = build_process_metrics_summary(
            range_key=range_key,
            depts=visible_depts,
            query=query,
        )

        if user_filters:
            snapshot["users"] = [
                row
                for row in snapshot.get("users", [])
                if str(row.get("user_id")) in user_filters
                or row.get("email") in user_filters
            ]

        available_users = snapshot.get("users", []) if not user_filters else []
        if user_filters:
            unfiltered = build_process_metrics_summary(
                range_key=range_key,
                depts=visible_depts,
                query=query,
            )
            available_users = unfiltered.get("users", [])

        dept_buckets = []
        for dept_metrics in snapshot["by_dept"]:
            dept_code = dept_metrics["dept"]
            dept_buckets.append(
                {
                    "dept": dept_code,
                    "metrics": dept_metrics,
                    "users": [
                        row
                        for row in snapshot["users"]
                        if (row.get("department") or "").strip().upper() == dept_code
                    ],
                    "interactions": [
                        row
                        for row in snapshot["interactions"]
                        if row.get("from_department") == dept_code
                        or row.get("to_department") == dept_code
                    ],
                }
            )

        return {
            "metrics": snapshot["by_dept"],
            "dept_buckets": dept_buckets,
            "users": snapshot["users"],
            "interactions": snapshot["interactions"],
            "summary": snapshot["summary"],
            "now": snapshot["now"],
            "cutoff": snapshot["cutoff"],
            "range_label": snapshot["range_label"],
            "range_key": snapshot["range_key"],
            "allowed_metric_departments": allowed_depts,
            "selected_metric_department": selected_dept,
            "q": query,
            "user_filters": user_filters,
            "available_users": available_users,
        }

    try:
        db.session.rollback()
    except Exception:
        pass

    try:
        cfg = MetricsConfig.get()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        cfg = MetricsConfig()

    form = MetricsConfigForm()
    if flask_request.method == "GET":
        form.enabled.data = bool(getattr(cfg, "enabled", True))
        form.track_request_created.data = bool(
            getattr(cfg, "track_request_created", True)
        )
        form.track_assignments.data = bool(getattr(cfg, "track_assignments", True))
        form.track_status_changes.data = bool(
            getattr(cfg, "track_status_changes", True)
        )
        form.lookback_days.data = int(getattr(cfg, "lookback_days", 30) or 30)
        form.user_metrics_limit.data = int(
            getattr(cfg, "user_metrics_limit", 15) or 15
        )
        form.target_completion_hours.data = int(
            getattr(cfg, "target_completion_hours", 48) or 48
        )
        form.slow_event_threshold_hours.data = int(
            getattr(cfg, "slow_event_threshold_hours", 8) or 8
        )

    if form.validate_on_submit():
        cfg.enabled = _submitted_checkbox_enabled("enabled")
        cfg.track_request_created = _submitted_checkbox_enabled(
            "track_request_created"
        )
        cfg.track_assignments = _submitted_checkbox_enabled("track_assignments")
        cfg.track_status_changes = _submitted_checkbox_enabled(
            "track_status_changes"
        )
        cfg.lookback_days = max(int(form.lookback_days.data or 30), 1)
        cfg.user_metrics_limit = max(int(form.user_metrics_limit.data or 15), 1)
        cfg.target_completion_hours = max(
            int(form.target_completion_hours.data or 48), 1
        )
        cfg.slow_event_threshold_hours = max(
            int(form.slow_event_threshold_hours.data or 8), 1
        )
        db.session.add(cfg)
        db.session.commit()
        flash("Metrics settings updated.", "success")
        return redirect(url_for("admin.metrics_config"))

    explorer = build_admin_metrics_explorer_context()
    return render_template(
        "admin_metrics_config.html",
        form=form,
        cfg=cfg,
        snapshot=build_process_metrics_summary(range_key="weekly", depts=["A", "B", "C"]),
        explorer=explorer,
    )


@admin_bp.route("/metrics_overview", methods=["GET"])
@login_required
def metrics_overview():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    from ..services.process_metrics import build_process_metrics_summary

    allowed_depts = ["A", "B", "C"]
    range_key = (flask_request.args.get("range") or "weekly").lower()
    selected_dept = (flask_request.args.get("dept") or "").strip().upper()
    visible_depts = [selected_dept] if selected_dept in allowed_depts else allowed_depts
    query = (flask_request.args.get("q") or "").strip()
    user_filters = flask_request.args.getlist("user")

    snapshot = build_process_metrics_summary(
        range_key=range_key,
        depts=visible_depts,
        query=query,
    )

    if user_filters:
        snapshot["users"] = [
            row
            for row in snapshot.get("users", [])
            if str(row.get("user_id")) in user_filters
            or row.get("email") in user_filters
        ]

    available_users = snapshot.get("users", []) if not user_filters else []
    if user_filters:
        unfiltered = build_process_metrics_summary(
            range_key=range_key,
            depts=visible_depts,
            query=query,
        )
        available_users = unfiltered.get("users", [])

    dept_buckets = []
    for dept_metrics in snapshot["by_dept"]:
        dept_code = dept_metrics["dept"]
        dept_buckets.append(
            {
                "dept": dept_code,
                "metrics": dept_metrics,
                "users": [
                    row
                    for row in snapshot["users"]
                    if (row.get("department") or "").strip().upper() == dept_code
                ],
                "interactions": [
                    row
                    for row in snapshot["interactions"]
                    if row.get("from_department") == dept_code
                    or row.get("to_department") == dept_code
                ],
            }
        )

    return render_template(
        "metrics.html",
        metrics=snapshot["by_dept"],
        dept_buckets=dept_buckets,
        users=snapshot["users"],
        interactions=snapshot["interactions"],
        summary=snapshot["summary"],
        now=snapshot["now"],
        cutoff=snapshot["cutoff"],
        range_label=snapshot["range_label"],
        range_key=snapshot["range_key"],
        allowed_metric_departments=allowed_depts,
        selected_metric_department=selected_dept,
        q=query,
        user_filters=user_filters,
        available_users=available_users,
        admin_metrics_mode=True,
        metrics_view_endpoint="admin.metrics_overview",
    )


@admin_bp.route("/reject_request_config", methods=["GET", "POST"])
@login_required
def reject_request_config():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    from .forms import RejectRequestConfigForm

    cfg = RejectRequestConfig.get()
    form = RejectRequestConfigForm()

    if flask_request.method == "GET":
        form.enabled.data = bool(getattr(cfg, "enabled", True))
        form.button_label.data = (
            getattr(cfg, "button_label", "Reject Request") or "Reject Request"
        )
        form.rejection_message.data = getattr(cfg, "rejection_message", None)
        form.dept_a_enabled.data = bool(getattr(cfg, "dept_a_enabled", False))
        form.dept_b_enabled.data = bool(getattr(cfg, "dept_b_enabled", True))
        form.dept_c_enabled.data = bool(getattr(cfg, "dept_c_enabled", False))

    if form.validate_on_submit():
        cfg.enabled = _submitted_checkbox_enabled("enabled")
        cfg.button_label = (form.button_label.data or "Reject Request").strip()[:120]
        cfg.rejection_message = (form.rejection_message.data or "").strip() or None
        cfg.dept_a_enabled = _submitted_checkbox_enabled("dept_a_enabled")
        cfg.dept_b_enabled = _submitted_checkbox_enabled("dept_b_enabled")
        cfg.dept_c_enabled = _submitted_checkbox_enabled("dept_c_enabled")
        db.session.commit()
        flash("Reject request configuration updated.", "success")
        return redirect(url_for("admin.reject_request_config"))

    return render_template("admin_reject_request_config.html", form=form, cfg=cfg)


@admin_bp.route("/departments")
@login_required
def list_departments():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    depts = Department.query.order_by(Department.code).all()
    return render_template("admin_departments.html", departments=depts)


@admin_bp.route("/migrations/status")
@login_required
def migration_status():
    """Admin helper: show applied DB alembic version(s) and migration files.

    This view is read-only and intended to help administrators detect
    unapplied migrations and provide the exact command to run (alembic upgrade head).
    """
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    try:
        inspector = db.inspect(db.engine)
    except Exception:
        current_app.logger.exception("Failed to inspect DB engine for migration status")
        flash(
            "Unable to inspect database engine. Check server logs.", "danger"
        )
        return render_template("admin_migration_status.html", status=None)

    # gather migration scripts from migrations/versions
    import os
    versions_dir = os.path.join(current_app.root_path, "..", "migrations", "versions")
    migrations = []
    try:
        for fn in sorted(os.listdir(versions_dir)):
            if fn.endswith('.py') and not fn.startswith('__'):
                migrations.append(fn[:-3])
    except Exception:
        migrations = []

    db_versions = []
    try:
        if inspector.has_table('alembic_version'):
            res = db.session.execute('SELECT version_num FROM alembic_version')
            db_versions = [r[0] for r in res.fetchall()]
    except Exception:
        current_app.logger.exception('Failed to read alembic_version table')

    status = {
        'migration_files': migrations,
        'db_versions': db_versions,
    }

    # Determine if any migration files look unapplied by comparing names.
    unapplied = [m for m in migrations if m not in db_versions]
    status['unapplied'] = unapplied

    return render_template("admin_migration_status.html", status=status)




@admin_bp.route("/dept_editors")
@login_required
def list_dept_editors():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    editors = DepartmentEditor.query.order_by(
        DepartmentEditor.department, DepartmentEditor.assigned_at.desc()
    ).all()
    return render_template("admin_dept_editors.html", editors=editors)


@admin_bp.route("/integrations")
@login_required
def list_integrations():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    ints = IntegrationConfig.query.order_by(
        IntegrationConfig.department, IntegrationConfig.kind
    ).all()
    summaries = {i.id: integration_config_summary(i.config) for i in ints}
    return render_template(
        "admin_integrations.html",
        integrations=ints,
        summaries=summaries,
    )




@admin_bp.route("/integrations/new", methods=["GET", "POST"])
@login_required
def create_integration():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    from .forms import IntegrationConfigForm

    form = IntegrationConfigForm()
    selected_kind = form.kind.data or (form.kind.choices[0][0] if form.kind.choices else "webhook")
    if form.validate_on_submit():
        try:
            normalized = normalize_integration_config(
                form.kind.data, form.config_json.data
            )
        except Exception as exc:
            flash(str(exc), "danger")
            scaffold = get_integration_scaffold(form.kind.data)
            return render_template(
                "admin_integration_edit.html",
                form=form,
                scaffold=scaffold,
                integration_scaffolds=INTEGRATION_KIND_SCAFFOLDS,
            )
        ic = IntegrationConfig(
            department=form.department.data,
            kind=form.kind.data,
            enabled=bool(form.enabled.data),
            config=json.dumps(normalized, indent=2),
        )
        db.session.add(ic)
        db.session.commit()
        flash("Integration saved.", "success")
        return redirect(url_for("admin.list_integrations"))
    if not form.config_json.data:
        form.config_json.data = json.dumps(
            get_integration_scaffold(selected_kind).get("default_config") or {},
            indent=2,
        )
    return render_template(
        "admin_integration_edit.html",
        form=form,
        scaffold=get_integration_scaffold(selected_kind),
        integration_scaffolds=INTEGRATION_KIND_SCAFFOLDS,
    )


@admin_bp.route("/integrations/<int:int_id>/edit", methods=["GET", "POST"])
@login_required
def edit_integration(int_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    from .forms import IntegrationConfigForm

    ic = get_or_404(IntegrationConfig, int_id)
    form = IntegrationConfigForm(obj=ic)
    if flask_request.method == "GET":
        try:
            normalized = normalize_integration_config(ic.kind, ic.config)
            form.config_json.data = json.dumps(normalized, indent=2)
        except Exception:
            form.config_json.data = ic.config or ""
    if form.validate_on_submit():
        try:
            normalized = normalize_integration_config(
                form.kind.data, form.config_json.data
            )
        except Exception as exc:
            flash(str(exc), "danger")
            return render_template(
                "admin_integration_edit.html",
                form=form,
                integration=ic,
                scaffold=get_integration_scaffold(form.kind.data),
                integration_scaffolds=INTEGRATION_KIND_SCAFFOLDS,
            )
        ic.department = form.department.data
        ic.kind = form.kind.data
        ic.enabled = bool(form.enabled.data)
        ic.config = json.dumps(normalized, indent=2)
        db.session.commit()
        flash("Integration updated.", "success")
        return redirect(url_for("admin.list_integrations"))
    return render_template(
        "admin_integration_edit.html",
        form=form,
        integration=ic,
        scaffold=get_integration_scaffold(ic.kind),
        integration_scaffolds=INTEGRATION_KIND_SCAFFOLDS,
    )


@admin_bp.route("/integrations/<int:int_id>/delete", methods=["POST"])
@login_required
def delete_integration(int_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    ic = get_or_404(IntegrationConfig, int_id)
    db.session.delete(ic)
    db.session.commit()
    flash("Integration removed.", "success")
    return redirect(url_for("admin.list_integrations"))


@admin_bp.route("/dept_editors/new", methods=["GET", "POST"])
@login_required
def create_dept_editor():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    from .forms import DepartmentEditorForm

    form = DepartmentEditorForm()
    # populate user choices
    form.user_id.choices = [
        (u.id, u.email) for u in User.query.order_by(User.email).all()
    ]
    if form.validate_on_submit():
        de = DepartmentEditor(
            user_id=form.user_id.data,
            department=form.department.data,
            can_edit=bool(form.can_edit.data),
            can_view_metrics=bool(form.can_view_metrics.data),
        )
        db.session.add(de)
        db.session.commit()
        flash("Department editor created.", "success")
        return redirect(url_for("admin.list_dept_editors"))
    return render_template("admin_dept_editor_edit.html", form=form)


@admin_bp.route("/dept_editors/<int:de_id>/delete", methods=["POST"])
@login_required
def delete_dept_editor(de_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    de = get_or_404(DepartmentEditor, de_id)
    db.session.delete(de)
    db.session.commit()
    flash("Department editor removed.", "success")
    return redirect(url_for("admin.list_dept_editors"))


@admin_bp.route("/departments/new", methods=["GET", "POST"])
@login_required
def create_department():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    form = DepartmentForm()
    if form.validate_on_submit():
        d = Department(
            code=form.code.data.upper(),
            label=form.name.data,
            description=None,
            is_active=bool(form.active.data),
            order=int(form.order.data or 0),
        )
        db.session.add(d)
        db.session.commit()
        flash("Department created.", "success")
        return redirect(url_for("admin.list_departments"))
    return render_template("admin_department_edit.html", form=form)


@admin_bp.route("/departments/<int:dept_id>/edit", methods=["GET", "POST"])
@login_required
def edit_department(dept_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    d = get_or_404(Department, dept_id)
    form = DepartmentForm(obj=d)
    if form.validate_on_submit():
        d.code = form.code.data.upper()
        d.label = form.name.data
        d.order = int(form.order.data or 0)
        d.is_active = bool(form.active.data)
        db.session.commit()
        flash("Department updated.", "success")
        return redirect(url_for("admin.list_departments"))
    return render_template("admin_department_edit.html", form=form, dept=d)


@admin_bp.route("/departments/<int:dept_id>/delete", methods=["POST"])
@login_required
def delete_department(dept_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    d = get_or_404(Department, dept_id)
    db.session.delete(d)
    db.session.commit()
    flash("Department deleted.", "success")
    return jsonify({"ok": True})
