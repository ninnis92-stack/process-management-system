from flask import Blueprint, render_template, redirect, url_for, flash, current_app, session, request as flask_request
from werkzeug.security import check_password_hash
try:
    import pyotp
except Exception:
    pyotp = None
from flask_login import login_user, logout_user, login_required, current_user

from .forms import LoginForm
from ..models import User
from ..extensions import db
from .sso import oauth
from .sso import token_has_mfa

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
            department="A",   # default for prototype
            is_active=True,
        )
        db.session.add(user)
    else:
        user.sso_sub = user.sso_sub or sub
        user.email = email
        user.name = name

    db.session.commit()

    if not user.is_active:
        return "Account disabled.", 403

    # If the IdP indicated MFA in the id_token, set a session flag used by admin checks
    try:
        if token_has_mfa(userinfo):
            session['sso_mfa'] = True
    except Exception:
        session.pop('sso_mfa', None)

    login_user(user)
    return redirect(url_for("requests.dashboard"))


# ---------- Local Login (fallback) ----------
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.strip().lower()).first()
        if not user or not user.is_active or not check_password_hash(user.password_hash, form.password.data):
            flash("Invalid credentials.", "danger")
            return render_template("login.html", form=form)

        # If user has TOTP enabled, require TOTP verification before completing login
        if getattr(user, 'totp_enabled', False):
            if pyotp is None:
                flash('Two-factor authentication is not available; contact an administrator.', 'danger')
            else:
                session['pre_2fa_userid'] = user.id
                return redirect(url_for('auth.totp_verify'))

        login_user(user)
        return redirect(url_for("requests.dashboard"))

    return render_template("login.html", form=form)


# ---------- Logout ----------
@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


# ---------- TOTP 2FA for local accounts ----------
@auth_bp.route('/totp/setup', methods=['GET', 'POST'])
@login_required
def totp_setup():
    if pyotp is None:
        flash('Two-factor authentication support is not installed on this instance.', 'warning')
        return redirect(url_for('requests.dashboard'))

    # Generate a secret and show provisioning URI; require confirmation with a code
    if flask_request.method == 'GET':
        secret = pyotp.random_base32()
        session['new_totp_secret'] = secret
        provisioning_uri = pyotp.totp.TOTP(secret).provisioning_uri(name=current_user.email, issuer_name=current_app.config.get('APP_NAME','ProcessMgmt'))
        return render_template('totp_setup.html', secret=secret, provisioning_uri=provisioning_uri)

    # POST: verify provided code and enable TOTP
    code = flask_request.form.get('code')
    secret = session.get('new_totp_secret')
    if not secret or not code:
        flash('Missing verification code.', 'danger')
        return redirect(url_for('auth.totp_setup'))

    if pyotp.TOTP(secret).verify(code):
        u = User.query.get(current_user.id)
        u.totp_secret = secret
        u.totp_enabled = True
        db.session.commit()
        session.pop('new_totp_secret', None)
        flash('Two-factor authentication enabled for your account.', 'success')
        return redirect(url_for('requests.dashboard'))

    flash('Invalid code; try again.', 'danger')
    return redirect(url_for('auth.totp_setup'))


@auth_bp.route('/totp/verify', methods=['GET', 'POST'])
def totp_verify():
    # Verify code for flow started after password login
    pre_id = session.get('pre_2fa_userid')
    if not pre_id:
        flash('No 2FA login pending.', 'warning')
        return redirect(url_for('auth.login'))

    u = User.query.get(pre_id)
    if not u:
        session.pop('pre_2fa_userid', None)
        flash('User not found.', 'danger')
        return redirect(url_for('auth.login'))

    if pyotp is None:
        flash('Two-factor authentication support is not installed on this instance.', 'warning')
        session.pop('pre_2fa_userid', None)
        return redirect(url_for('auth.login'))

    if flask_request.method == 'GET':
        return render_template('totp_verify.html')

    code = flask_request.form.get('code')
    if not code:
        flash('Enter the code from your authenticator app.', 'warning')
        return render_template('totp_verify.html')

    if not u.totp_secret:
        flash('2FA not configured for this account.', 'danger')
        session.pop('pre_2fa_userid', None)
        return redirect(url_for('auth.login'))

    if pyotp.TOTP(u.totp_secret).verify(code):
        # Successful, complete login
        session.pop('pre_2fa_userid', None)
        login_user(u)
        session['totp_verified'] = True
        return redirect(url_for('requests.dashboard'))

    flash('Invalid code.', 'danger')
    return render_template('totp_verify.html')


@auth_bp.route('/vibe', methods=['POST'])
@login_required
def set_vibe():
    """Persist per-user vibe/theme index (expects form or JSON 'vibe_index')."""
    try:
        v = None
        if flask_request.is_json:
            data = flask_request.get_json()
            v = int(data.get('vibe_index'))
        else:
            v = int(flask_request.form.get('vibe_index'))
    except Exception:
        return ("Invalid payload", 400)

    if v is None:
        return ("Missing vibe_index", 400)

    u = User.query.get(current_user.id)
    u.vibe_index = max(0, int(v))
    db.session.commit()
    return ({'ok': True}, 200)