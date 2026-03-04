from flask import Blueprint, render_template, redirect, url_for, flash, current_app
from werkzeug.security import check_password_hash
from flask_login import login_user, logout_user, login_required

from .forms import LoginForm
from ..models import User
from ..extensions import db
from .sso import oauth

auth_bp = Blueprint("auth", __name__, url_pre***REMOVED***x="/auth")


# ---------- SSO ----------
# Keep SSO endpoints ready; falls back to local auth until the IdP con***REMOVED***g is fully wired.
@auth_bp.route("/sso/login")
def sso_login():
    if not current_app.con***REMOVED***g.get("SSO_ENABLED"):
        return redirect(url_for("auth.login"))  # fallback to local login

    if not hasattr(oauth, "oidc"):
        flash("SSO is not fully con***REMOVED***gured. Using local login.", "warning")
        return redirect(url_for("auth.login"))

    redirect_uri = current_app.con***REMOVED***g.get("OIDC_REDIRECT_URI")
    if not redirect_uri:
        flash("SSO redirect not con***REMOVED***gured.", "warning")
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

    user = User.query.***REMOVED***lter((User.sso_sub == sub) | (User.email == email)).***REMOVED***rst()

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

    login_user(user)
    return redirect(url_for("requests.dashboard"))


# ---------- Local Login (fallback) ----------
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.***REMOVED***lter_by(email=form.email.data.strip().lower()).***REMOVED***rst()
        if not user or not user.is_active or not check_password_hash(user.password_hash, form.password.data):
            flash("Invalid credentials.", "danger")
            return render_template("login.html", form=form)

        login_user(user)
        return redirect(url_for("requests.dashboard"))

    return render_template("login.html", form=form)


# ---------- Logout ----------
@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))