from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    current_app,
    session,
    request,
    jsonify,
)
from werkzeug.security import check_password_hash

try:
    import pyotp
except Exception:
    pyotp = None
from flask_login import login_user, logout_user, login_required, current_user

from .forms import LoginForm, SettingsForm
from ..models import User
from ..models import FeatureFlags
from ..extensions import db
from .sso import oauth
from .sso import token_has_mfa
from .sso import sso_user_is_admin
from .sso import sso_user_department
from sqlalchemy.exc import OperationalError
from flask import session as _session
from ..models import UserDepartment, Department
from ..services.tenant_context import ensure_user_tenant_membership, set_active_tenant
from ..security import rate_limit
from ..utils.user_context import (
    get_user_departments,
    is_external_theme_active,
    user_can_access_department,
)


def _restore_last_active_dept_for_user(user):
    """If the user has a persisted `last_active_dept`, and they are allowed
    to view as that department, set it into the session so the app will
    present that department on login.
    """
    if not user:
        return
    try:
        dept = (getattr(user, "last_active_dept", None) or "").strip().upper()
        if not dept:
            return

        # Validate department exists and user is allowed
        d = Department.query.filter_by(code=dept, is_active=True).first()
        if not d:
            return

        allowed = user_can_access_department(user, dept)

        if allowed:
            try:
                current_app.logger.info(
                    "Restoring last_active_dept for user %s -> %s",
                    getattr(user, "email", getattr(user, "id", "unknown")),
                    dept,
                )
            except Exception:
                pass
            _session["active_dept"] = dept
    except Exception:
        try:
            current_app.logger.exception(
                "Failed to restore last_active_dept for user %s",
                getattr(user, "email", getattr(user, "id", "unknown")),
            )
        except Exception:
            pass
        # Fail silently; restoring department is a convenience only.
        return


def _setting_present(payload, key):
    try:
        return key in payload
    except Exception:
        return False


def _coerce_checkbox_value(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() not in ("", "0", "false", "off", "no")


def _sync_current_user_preferences(user):
    try:
        current_user.dark_mode = bool(getattr(user, "dark_mode", False))
        current_user.quotes_enabled = bool(getattr(user, "quotes_enabled", True))
        current_user.vibe_index = getattr(user, "vibe_index", None)
        current_user.quote_set = getattr(user, "quote_set", None)
        current_user.quote_interval = getattr(user, "quote_interval", None)
    except Exception:
        pass


VIBE_PALETTE_CHOICES = [
    (0, "Soft Coral · Cozy Coral"),
    (1, "Warm Sand · Warm Morning"),
    (2, "Moss · Quiet Grove"),
    (3, "Sage · Sage Retreat"),
    (4, "Muted Teal · Calm Teal"),
    (5, "Sky · Clear Sky"),
    (6, "Powder Blue · Soft Powder"),
    (7, "Lavender · Lavender Dream"),
    (8, "Lilac · Lilac Haze"),
    (9, "Muted Pink · Blush"),
    (10, "Peach · Peach Sunrise"),
    (11, "Butter · Buttercream"),
    (12, "Pistachio · Pistachio Grove"),
    (13, "Mint · Fresh Mint"),
    (14, "Seafoam · Seafoam Breeze"),
    (15, "Aqua · Aqua Calm"),
    (16, "Robin Egg · Robin's Dawn"),
    (17, "Periwinkle · Periwinkle Morning"),
    (18, "Dusty Blue · Dusty Blue"),
    (19, "Slate Rose · Slate Rose"),
    (20, "Tea · Tea Garden"),
    (21, "Stone · Stone Whisper"),
    (22, "Soft Gray · Soft Gray"),
    (23, "Charcoal Mist · Charcoal Mist"),
    (24, "Aurora · Aurora"),
]

DARK_MODE_COMPATIBLE_VIBE_INDEXES = (0, 4, 5, 7, 14, 18, 23, 24)


def _is_dark_mode_compatible_vibe(vibe_index):
    try:
        return int(vibe_index) in DARK_MODE_COMPATIBLE_VIBE_INDEXES
    except Exception:
        return False


def _normalize_vibe_index(vibe_index, *, dark_mode=False):
    try:
        parsed = int(vibe_index)
    except Exception:
        parsed = None

    if not dark_mode:
        return parsed

    if parsed is None or parsed not in DARK_MODE_COMPATIBLE_VIBE_INDEXES:
        return DARK_MODE_COMPATIBLE_VIBE_INDEXES[0]
    return parsed


def _apply_user_preference_updates(user, payload, *, external_theme_loaded=None, partial=False):
    if not user or payload is None:
        return {}

    if external_theme_loaded is None:
        external_theme_loaded = is_external_theme_active()

    updated = {}

    if _setting_present(payload, "dark_mode") or _setting_present(payload, "dark_mode_present"):
        user.dark_mode = _coerce_checkbox_value(payload.get("dark_mode"))
        updated["dark_mode"] = bool(user.dark_mode)

    if _setting_present(payload, "quotes_enabled") or _setting_present(payload, "quotes_enabled_present"):
        user.quotes_enabled = _coerce_checkbox_value(payload.get("quotes_enabled"))
        updated["quotes_enabled"] = bool(user.quotes_enabled)

    if not external_theme_loaded and _setting_present(payload, "vibe_index"):
        raw_vibe = payload.get("vibe_index")
        if raw_vibe in (None, ""):
            user.vibe_index = None if not bool(getattr(user, "dark_mode", False)) else DARK_MODE_COMPATIBLE_VIBE_INDEXES[0]
        else:
            try:
                user.vibe_index = _normalize_vibe_index(raw_vibe, dark_mode=bool(getattr(user, "dark_mode", False)))
            except Exception:
                pass
        updated["vibe_index"] = getattr(user, "vibe_index", None)

    # if dark mode is active, clear any vibe index so that the theme is
    # effectively disabled.  this mirrors client-side behavior where the
    # controls are non-functional and no accenting is applied.
    if bool(getattr(user, "dark_mode", False)):
        user.vibe_index = None
        updated["vibe_index"] = None

    if _setting_present(payload, "quote_set"):
        quote_set = payload.get("quote_set")
        user.quote_set = (str(quote_set).strip() or None) if quote_set is not None else None
        updated["quote_set"] = getattr(user, "quote_set", None)

    if _setting_present(payload, "quote_interval"):
        raw_interval = payload.get("quote_interval")
        try:
            user.quote_interval = int(raw_interval) if str(raw_interval or "").strip() else None
        except Exception:
            pass
        updated["quote_interval"] = getattr(user, "quote_interval", None)

    return updated


def _get_user_departments(user):
    """Return a list of department codes the user may act as.

    Primary department is first, followed by any explicit `UserDepartment`
    assignments (preserving order and uniqueness).
    """
    return get_user_departments(user)


def _sync_primary_department_from_sso(user, userinfo):
    if not user:
        return
    try:
        flags = None
        try:
            flags = FeatureFlags.get()
        except Exception:
            flags = None

        sync_enabled = bool(
            getattr(
                flags,
                "sso_department_sync_enabled",
                current_app.config.get("SSO_DEPARTMENT_SYNC_ENABLED", False),
            )
        )
        if not sync_enabled or getattr(user, "department_override", False):
            return

        resolved_department = sso_user_department(userinfo, current_app.config)
        if resolved_department and getattr(user, "department", None) != resolved_department:
            user.department = resolved_department
    except Exception:
        current_app.logger.exception(
            "Failed to sync SSO primary department for %s",
            getattr(user, "email", getattr(user, "id", "unknown")),
        )


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# ---------- SSO ----------
# Keep SSO endpoints ready; falls back to local auth until the IdP config is fully wired.
@auth_bp.route("/sso/login")
def sso_login():
    if not current_app.config.get("SSO_ENABLED"):
        return redirect(url_for("auth.login"))  # fallback to local login

    if not hasattr(oauth, "oidc"):
        flash("SSO is not fully configured. Using local login.", "warning")
        return redirect(url_for("auth.login"))

    redirect_uri = current_app.config.get("OIDC_REDIRECT_URI")
    if not redirect_uri:
        flash("SSO redirect not configured.", "warning")
        return redirect(url_for("auth.login"))

    return oauth.oidc.authorize_redirect(redirect_uri)


@auth_bp.route("/sso/callback")
def sso_callback():
    if not hasattr(oauth, "oidc"):
        flash("SSO not available.", "danger")
        return redirect(url_for("auth.login"))

    try:
        token = oauth.oidc.authorize_access_token()
        userinfo = oauth.oidc.parse_id_token(token)
    except Exception as e:  # noqa: BLE001
        current_app.logger.exception("SSO callback failed")
        flash("SSO login failed.", "danger")
        return redirect(url_for("auth.login"))

    sub = userinfo.get("sub")
    email = (userinfo.get("email") or "").lower().strip()
    name = userinfo.get("name")

    if not email:
        return "SSO login failed: no email claim.", 400

    user = User.query.filter((User.sso_sub == sub) | (User.email == email)).first()

    if not user:
        user = User(
            sso_sub=sub,
            email=email,
            name=name,
            department="A",  # default for prototype
            is_active=True,
        )
        db.session.add(user)
    else:
        user.sso_sub = user.sso_sub or sub
        user.email = email
        user.name = name

    # Synchronize admin privileges from organization-managed SSO settings.
    # Non-strict mode only elevates recognized admins; strict mode mirrors the
    # configured SSO decision on every login.
    try:
        flags = None
        try:
            flags = FeatureFlags.get()
        except Exception:
            flags = None

        sso_sync_enabled = bool(
            getattr(
                flags,
                "sso_admin_sync_enabled",
                current_app.config.get("SSO_ADMIN_SYNC_ENABLED", True),
            )
        )
        if sso_sync_enabled:
            recognized_admin = sso_user_is_admin(
                userinfo, current_app.config, email=email
            )
            if recognized_admin:
                user.is_admin = True
            elif current_app.config.get("SSO_ADMIN_SYNC_STRICT", False):
                user.is_admin = False
    except Exception:
        current_app.logger.exception("Failed to sync SSO admin role for %s", email)

    _sync_primary_department_from_sso(user, userinfo)

    db.session.commit()

    tenant = ensure_user_tenant_membership(user)
    if tenant:
        set_active_tenant(tenant)

    if not user.is_active:
        return "Account disabled.", 403

    # If the IdP indicated MFA in the id_token, set a session flag used by admin checks
    try:
        if token_has_mfa(userinfo, current_app.config):
            session["sso_mfa"] = True
    except Exception:
        session.pop("sso_mfa", None)

    login_user(user)
    # admins always land on the command center by default; this happens before
    # any department-selection logic so that they never get kicked back to the
    # /auth/choose_dept page.  We still respect a `next` URL if present so that
    # automated flows continue to work.
    if getattr(user, "is_admin", False):
        next_url = request.args.get('next') or request.form.get('next')
        if next_url and next_url.startswith('/') and not next_url.startswith('//'):
            return redirect(next_url)
        return redirect(url_for("admin.index"))
    try:
        depts = _get_user_departments(user)
        if len(depts) > 1:
            return redirect(url_for("auth.choose_dept"))
        if getattr(user, "last_active_dept", None):
            _restore_last_active_dept_for_user(user)
        else:
            _session["active_dept"] = (
                depts[0] if depts else getattr(user, "department", None)
            )
    except Exception:
        pass
    return redirect(url_for("requests.dashboard"))


@auth_bp.route("/choose_dept", methods=["GET"])
@login_required
def choose_dept():
    """Render the department selection page when a user has multiple departments."""
    if getattr(current_user, "is_admin", False):
        flash("Admins manage departments from the command center.", "info")
        return redirect(url_for("admin.index"))
    depts = _get_user_departments(current_user)
    return render_template("choose_department.html", departments=depts)


@auth_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    """Per-user settings page (theme/preferences)."""
    form = SettingsForm(obj=current_user)
    all_palettes = list(VIBE_PALETTE_CHOICES)
    dark_mode_palettes = [choice for choice in all_palettes if choice[0] in DARK_MODE_COMPATIBLE_VIBE_INDEXES]
    form.vibe_index.choices = dark_mode_palettes if bool(getattr(current_user, "dark_mode", False)) else all_palettes
    form.vibe_index.data = _normalize_vibe_index(
        getattr(current_user, "vibe_index", None),
        dark_mode=bool(getattr(current_user, "dark_mode", False)),
    )
    # populate quote-set choices from site config defaults
    try:
        from ..models import SiteConfig

        cfg = SiteConfig.get()
        sets = (
            cfg.allowed_quote_set_names_for_user(current_user)
            if cfg
            else list(SiteConfig.DEFAULT_QUOTE_SETS.keys())
        )
    except Exception:
        sets = list(SiteConfig.DEFAULT_QUOTE_SETS.keys())
    # simple label = key
    form.quote_set.choices = [("", "(use site default)")] + [
        (s, s.capitalize()) for s in sets
    ]

    # prepare interval options (15‑60 seconds in 5‑second increments)
    iv_choices = [(i, f"{i} seconds") for i in range(15, 61, 5)]
    form.quote_interval.choices = [("", "(use default)")] + iv_choices
    # quote interval choices already defined on the form; preselect user's
    # current value if available or fall back to site default
    try:
        if hasattr(current_user, 'quote_interval') and current_user.quote_interval:
            form.quote_interval.data = current_user.quote_interval
        else:
            # use site config default
            cfg = SiteConfig.get()
            form.quote_interval.data = getattr(cfg, 'rolling_quote_interval_default', 8)
    except Exception:
        form.quote_interval.data = None
    if form.validate_on_submit():
        try:
            u = db.session.get(User, current_user.id)
            if u:
                _apply_user_preference_updates(
                    u,
                    request.form,
                    external_theme_loaded=is_external_theme_active(),
                    partial=False,
                )
                db.session.add(u)
                db.session.commit()
                _sync_current_user_preferences(u)
                flash("Settings saved.", "success")
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            flash("Failed to save settings.", "danger")
        return redirect(url_for("requests.dashboard"))

    return render_template(
        "settings.html",
        form=form,
        all_vibe_choices=all_palettes,
    )


@auth_bp.route("/preferences", methods=["POST"])
@login_required
def set_preferences():
    """Persist one or more user account preferences immediately."""
    payload = request.get_json(silent=True) if request.is_json else request.form
    try:
        u = db.session.get(User, current_user.id)
        if not u:
            return jsonify({"ok": False, "error": "user_not_found"}), 404

        updated = _apply_user_preference_updates(
            u,
            payload,
            external_theme_loaded=is_external_theme_active(),
            partial=True,
        )
        db.session.add(u)
        db.session.commit()
        _sync_current_user_preferences(u)
        return jsonify({"ok": True, "preferences": updated})
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({"ok": False, "error": "save_failed"}), 500


@auth_bp.route("/preferences/dark-mode", methods=["POST"])
@login_required
def set_dark_mode_preference():
    """Compatibility wrapper for the dedicated dark-mode endpoint."""
    response = set_preferences()
    try:
        body, status = response
    except Exception:
        body = response
        status = 200
    try:
        payload = body.get_json() if hasattr(body, "get_json") else None
        if isinstance(payload, dict) and payload.get("ok") is True:
            prefs = payload.get("preferences") or {}
            payload["dark_mode"] = prefs.get("dark_mode", False)
            return jsonify(payload), status
    except Exception:
        pass
    return response


@auth_bp.route("/departments", methods=["GET"])
@login_required
def list_departments():
    """Return JSON list of departments the current user may switch to.

    Always includes the user's primary department. Admins may see all active
    departments.
    """
    try:
        depts = get_user_departments(current_user)
        return jsonify({"departments": depts})
    except Exception:
        return jsonify({"departments": [getattr(current_user, "department", None)]})


@auth_bp.route("/switch_dept", methods=["POST"])
@login_required
def switch_department():
    """Set the user's active department in session if allowed."""
    data = None
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form
    dept = (data.get("department") or "").strip().upper()
    if not dept:
        return ("Missing department", 400)

    # Validate department exists and is active
    try:
        d = Department.query.filter_by(code=dept, is_active=True).first()
        if not d:
            return ("Unknown department", 404)
    except Exception:
        return ("Service unavailable", 503)

    # Allowed if primary, explicitly assigned, or admin
    allowed = user_can_access_department(current_user, dept)

    if not allowed:
        return ("Not allowed to view that department", 403)

    _session["active_dept"] = dept
    # Persist the user's preference
    try:
        if getattr(current_user, "id", None):
            u = db.session.get(User, current_user.id)
            if u:
                u.last_active_dept = dept
                db.session.add(u)
                db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

    # For convenience return JSON for AJAX callers
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "active_dept": dept})
    # if we landed here from the login flow and a next-url was preserved,
    # redirect there now that the department has been chosen
    next_url = _session.pop('next_after_choose_dept', None)
    if next_url and isinstance(next_url, str) and next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)
    return redirect(url_for("requests.dashboard"))


# ---------- Local Login (fallback) ----------
@auth_bp.route("/login", methods=["GET", "POST"])
@rate_limit("login", config_key="LOGIN_RATE_LIMIT", default="5/300")
def login():
    form = LoginForm()
    # Clear any pre-filled email when rendering the login page via GET so
    # refreshing the page doesn't leave the previous email visible in the form.
    if request.method == "GET":
        try:
            form.email.data = ""
        except Exception:
            pass
    if form.validate_on_submit():
        try:
            email = (form.email.data or "").strip().lower()
            user = User.query.filter(db.func.lower(User.email) == email).first()
        except OperationalError as err:
            try:
                current_app.logger.exception("Database unavailable during login")
            except Exception:
                pass
            try:
                db.session.rollback()
            except Exception:
                try:
                    current_app.logger.exception(
                        "Failed to rollback after OperationalError in login"
                    )
                except Exception:
                    pass
            flash("Temporary database error. Please try again shortly.", "warning")
            return render_template("login.html", form=form)
        except Exception as err:
            try:
                current_app.logger.exception("Unexpected DB error during login")
            except Exception:
                pass
            try:
                db.session.rollback()
            except Exception:
                try:
                    current_app.logger.exception(
                        "Failed to rollback after unexpected error in login"
                    )
                except Exception:
                    pass
            flash("Temporary database error. Please try again shortly.", "warning")
            return render_template("login.html", form=form)
        if (
            not user
            or not user.is_active
            or not check_password_hash(user.password_hash, form.password.data)
        ):
            # Add a form-level error so the template can display it near the fields
            form.password.errors.append("Invalid email or password")
            return render_template("login.html", form=form), 401

        # If user has TOTP enabled, require TOTP verification before completing login
        if getattr(user, "totp_enabled", False):
            if pyotp is None:
                flash(
                    "Two-factor authentication is not available; contact an administrator.",
                    "danger",
                )
            else:
                session["pre_2fa_userid"] = user.id
                return redirect(url_for("auth.totp_verify"))

        try:
            login_user(user)
            tenant = ensure_user_tenant_membership(user)
            if tenant:
                set_active_tenant(tenant)
            # redirect admins immediately to the command center; skip department flow
            if getattr(user, "is_admin", False):
                next_url = request.args.get('next') or request.form.get('next')
                if next_url:
                    from urllib.parse import urlparse

                    parsed = urlparse(next_url)
                    if parsed.path and parsed.path.startswith('/') and not parsed.path.startswith('//'):
                        if not parsed.path.startswith('/static/'):
                            return redirect(next_url)
                return redirect(url_for("admin.index"))
        except Exception:
            try:
                current_app.logger.exception(
                    "Failed during login_user() for %s",
                    getattr(user, "email", getattr(user, "id", "unknown")),
                )
            except Exception:
                pass
            try:
                db.session.rollback()
            except Exception:
                pass
            flash("Login failed due to an internal error; try again.", "danger")
            return render_template("login.html", form=form)
        # If the user has multiple departments available, prompt them to choose;
        # otherwise restore last-active or set primary department into session.
        try:
            depts = _get_user_departments(user)
            # unlike earlier versions, we no longer force a dedicated
            # /auth/choose_dept step when a user can select departments via
            # the navbar dropdown (admins and multi-dept users).  simply
            # default to the first department and let the picker handle
            # further switches.
            restored = False
            if getattr(user, "last_active_dept", None):
                try:
                    _restore_last_active_dept_for_user(user)
                    restored = True
                except Exception:
                    restored = False
            if not restored:
                _session["active_dept"] = (
                    depts[0] if depts else getattr(user, "department", None)
                )
        except Exception:
            pass
        # Respect a `next` parameter when redirecting after login.  Only
        # allow internal paths to avoid open-redirect attacks.
        next_url = request.args.get('next') or request.form.get('next')
        # ignore attempts to redirect to static assets (common when a CSS/JS
        # file is fetched while session has expired and login_required kicks in).
        if next_url:
            from urllib.parse import urlparse

            parsed = urlparse(next_url)
            # only allow same-host/internal paths
            if parsed.path and parsed.path.startswith('/') and not parsed.path.startswith('//'):
                if not parsed.path.startswith('/static/'):
                    return redirect(next_url)
        return redirect(url_for("requests.dashboard"))

    return render_template("login.html", form=form)


# ---------- Logout ----------
@auth_bp.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    # Persist the last active department (if any) for this user so it can be
    # restored on next login.
    try:
        active = _session.get("active_dept")
        if active and getattr(current_user, "id", None):
            u = db.session.get(User, current_user.id)
            if u:
                u.last_active_dept = active
                db.session.add(u)
                db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
    logout_user()
    return redirect(url_for("auth.login"))


# ---------- TOTP 2FA for local accounts ----------
@auth_bp.route("/totp/setup", methods=["GET", "POST"])
@login_required
def totp_setup():
    if pyotp is None:
        flash(
            "Two-factor authentication support is not installed on this instance.",
            "warning",
        )
        return redirect(url_for("requests.dashboard"))

    # Generate a secret and show provisioning URI; require confirmation with a code
    if request.method == "GET":
        secret = pyotp.random_base32()
        session["new_totp_secret"] = secret
        provisioning_uri = pyotp.totp.TOTP(secret).provisioning_uri(
            name=current_user.email,
            issuer_name=current_app.config.get("APP_NAME", "ProcessMgmt"),
        )
        return render_template(
            "totp_setup.html", secret=secret, provisioning_uri=provisioning_uri
        )

    # POST: verify provided code and enable TOTP
    code = request.form.get("code")
    secret = session.get("new_totp_secret")
    if not secret or not code:
        flash("Missing verification code.", "danger")
        return redirect(url_for("auth.totp_setup"))

    if pyotp.TOTP(secret).verify(code):
        u = db.session.get(User, current_user.id)
        u.totp_secret = secret
        u.totp_enabled = True
        db.session.commit()
        session.pop("new_totp_secret", None)
        flash("Two-factor authentication enabled for your account.", "success")
        return redirect(url_for("requests.dashboard"))

    flash("Invalid code; try again.", "danger")
    return redirect(url_for("auth.totp_setup"))


@auth_bp.route("/totp/verify", methods=["GET", "POST"])
def totp_verify():
    # Verify code for flow started after password login
    pre_id = session.get("pre_2fa_userid")
    if not pre_id:
        flash("No 2FA login pending.", "warning")
        return redirect(url_for("auth.login"))

    u = db.session.get(User, pre_id)
    if not u:
        session.pop("pre_2fa_userid", None)
        flash("User not found.", "danger")
        return redirect(url_for("auth.login"))

    if pyotp is None:
        flash(
            "Two-factor authentication support is not installed on this instance.",
            "warning",
        )
        session.pop("pre_2fa_userid", None)
        return redirect(url_for("auth.login"))

    if request.method == "GET":
        return render_template("totp_verify.html")

    code = request.form.get("code")
    if not code:
        flash("Enter the code from your authenticator app.", "warning")
        return render_template("totp_verify.html")

    if not u.totp_secret:
        flash("2FA not configured for this account.", "danger")
        session.pop("pre_2fa_userid", None)
        return redirect(url_for("auth.login"))

    if pyotp.TOTP(u.totp_secret).verify(code):
        # Successful, complete login
        session.pop("pre_2fa_userid", None)
        login_user(u)
        session["totp_verified"] = True
        # TOTP flow also honours admin landing
        if getattr(u, "is_admin", False):
            return redirect(url_for("admin.index"))
        try:
            depts = _get_user_departments(u)
            # same logic during 2FA login path; skip explicit chooser even if
            # multiple departments are available.
            if getattr(u, "last_active_dept", None):
                _restore_last_active_dept_for_user(u)
            else:
                _session["active_dept"] = (
                    depts[0] if depts else getattr(u, "department", None)
                )
        except Exception:
            pass
        return redirect(url_for("requests.dashboard"))

    flash("Invalid code.", "danger")
    return render_template("totp_verify.html")


@auth_bp.route("/vibe", methods=["POST"])
@login_required
def set_vibe():
    """Persist per-user vibe/theme index (expects form or JSON 'vibe_index')."""
    try:
        v = None
        if request.is_json:
            data = request.get_json()
            v = int(data.get("vibe_index"))
        else:
            v = int(request.form.get("vibe_index"))
    except Exception:
        return ("Invalid payload", 400)

    if v is None:
        return ("Missing vibe_index", 400)

    u = db.session.get(User, current_user.id)
    if getattr(u, "dark_mode", False):
        # when dark mode is enabled we don't allow changing or storing a custom
        # vibe; the client side should already have disabled the controls.
        return jsonify({"ok": False, "error": "dark_mode_vibe_disabled"}), 409
    u.vibe_index = _normalize_vibe_index(max(0, int(v)), dark_mode=False)
    db.session.commit()
    # Reflect change in current_user proxy for immediate client-side use
    _sync_current_user_preferences(u)
    return ({"ok": True, "vibe_index": u.vibe_index}, 200)
