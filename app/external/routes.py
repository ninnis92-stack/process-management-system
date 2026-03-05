import smtplib
from email.message import EmailMessage
from flask import Blueprint, render_template, redirect, url_for, flash, abort, current_app

from ..extensions import db
from ..models import Artifact, Request as ReqModel, Comment, AuditLog, Submission, User, Notification
from ..notifcations import notify_users, users_in_department
from .forms import ExternalNewRequestForm, ExternalCommentForm, GuestLookupForm

external_bp = Blueprint("external", __name__, url_prefix="/external")

def _log(req, action_type, note=None, from_status=None, to_status=None, actor_type="guest", actor_label=None):
    entry = AuditLog(
        request_id=req.id,
        actor_type=actor_type,
        actor_user_id=None,
        actor_label=actor_label,
        action_type=action_type,
        from_status=from_status,
        to_status=to_status,
        note=note,
    )
    db.session.add(entry)

# Notification helpers imported from app/notifcations.py


def _send_guest_email(to_email: str, subject: str, body: str) -> None:
    host = current_app.config.get("SMTP_HOST")
    port = current_app.config.get("SMTP_PORT", 587)
    username = current_app.config.get("SMTP_USERNAME")
    password = current_app.config.get("SMTP_PASSWORD")
    from_email = current_app.config.get("MAIL_FROM", username)
    use_tls = current_app.config.get("SMTP_USE_TLS", True)

    if not host or not from_email:
        current_app.logger.warning("Email not sent: SMTP_HOST or MAIL_FROM not configured")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port) as server:
            if use_tls:
                server.starttls()
            if username and password:
                server.login(username, password)
            server.send_message(msg)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("Failed to send guest email", exc_info=exc)

@external_bp.route("/new", methods=["GET", "POST"])
def external_new():
    form = ExternalNewRequestForm()
    if form.validate_on_submit():
        desc = (form.description.data or "").strip()

        req = ReqModel(
            title=form.title.data.strip(),
            request_type=form.request_type.data,
            description=desc,
            priority=form.priority.data,
            requires_c_review=False,
            status="NEW_FROM_A",
            owner_department="B",
            submitter_type="guest",
            guest_email=form.guest_email.data.strip().lower(),
            guest_name=form.guest_name.data.strip() if form.guest_name.data else None,
            pricebook_status=form.pricebook_status.data,
            due_at=form.due_at.data,
        )
        req.ensure_guest_token()
        db.session.add(req)
        db.session.flush()  # req.id available now

        dept_users = users_in_department(req.owner_department)
        notify_users(
            dept_users,
            title=f"New guest request submitted (Request #{req.id})",
            body=req.title,
            url=url_for("requests.request_detail", request_id=req.id),
            ntype="new_request",
            request_id=req.id,
        )

        donor = (form.donor_part_number.data or "").strip() or None
        target = (form.target_part_number.data or "").strip() or None
        reason = (form.no_donor_reason.data or "").strip() or None

        # Auto-create artifact(s) based on request type
        if form.request_type.data in ("part_number", "both"):
            a1 = Artifact(
                request_id=req.id,
                artifact_type="part_number",
                donor_part_number=donor,
                target_part_number=target,  # optional
                no_donor_reason=reason if form.request_type.data == "part_number" else None,
                instructions_url=None,
                created_by_user_id=None,
                created_by_department="A",
                created_by_guest_email=req.guest_email,
            )
            db.session.add(a1)

        if form.request_type.data in ("instructions", "both"):
            a2 = Artifact(
                request_id=req.id,
                artifact_type="instructions",
                donor_part_number=donor,     # required by your validation for instructions/both
                target_part_number=target,   # required for instructions; optional for both if you chose that
                no_donor_reason=None,
                instructions_url=None,
                created_by_user_id=None,
                created_by_department="A",
                created_by_guest_email=req.guest_email,
            )
            db.session.add(a2)

        _log(req, "created", note="Request created by Guest.", to_status=req.status, actor_label=req.guest_email)

        sub = Submission(
            request_id=req.id,
            from_department="A",
            to_department="B",
            from_status="NEW_FROM_A",
            to_status="NEW_FROM_A",
            summary="Initial submission (Guest)",
            details=desc,
            is_public_to_submitter=True,
            created_by_guest_email=req.guest_email,
        )
        db.session.add(sub)
        _log(req, "submission_created", note="Initial submission packet created (Guest A→B).", actor_label=req.guest_email)

        db.session.commit()
        
        # Email the guest with their request number and tracking link (best-effort)
        link = url_for("external.external_detail", token=req.guest_access_token, _external=True)
        _send_guest_email(
            req.guest_email,
            subject=f"Your request #{req.id}",
            body=f"Thanks for submitting your request. Your request number is #{req.id}.\n\nTrack it here: {link}\n",
        )
        flash(f"Request #{req.id} submitted successfully. You can use this page to track updates.", "success")
        return redirect(url_for("external.external_detail", token=req.guest_access_token))

    return render_template("external_new.html", form=form)


@external_bp.route("/dashboard", methods=["GET", "POST"])
def external_dashboard():
    form = GuestLookupForm()
    if form.validate_on_submit():
        rid = form.request_id.data
        email = (form.guest_email.data or "").strip().lower()
        # If a request id was provided, maintain existing behavior
        if rid:
            req = ReqModel.query.filter_by(id=rid, submitter_type="guest").first()
            if not req:
                flash("Request not found.", "warning")
            elif (req.guest_email or "").lower() != email:
                flash("Email does not match this request.", "warning")
            else:
                return redirect(url_for("external.external_detail", token=req.guest_access_token))
        else:
            # No request id: list all open guest requests for this email
            results = ReqModel.query.filter(
                ReqModel.submitter_type == 'guest',
                func.lower(ReqModel.guest_email) == email,
                ReqModel.status != 'CLOSED'
            ).order_by(ReqModel.updated_at.desc()).all()
            if not results:
                flash("No open requests found for this email.", "warning")
            else:
                return render_template('external_dashboard.html', form=form, results=results)

    return render_template("external_dashboard.html", form=form)

def _get_req_by_token(token: str) -> ReqModel:
    req = ReqModel.query.filter_by(guest_access_token=token).first()
    if not req:
        abort(404)
    return req

@external_bp.route("/<token>", methods=["GET", "POST"])
def external_detail(token: str):
    req = _get_req_by_token(token)

    public_comments = Comment.query.filter_by(request_id=req.id, visibility_scope="public").order_by(Comment.created_at.asc()).all()
    public_submissions = [s for s in req.submissions if s.is_public_to_submitter]
    public_audit = list(req.audit_logs)

    form = ExternalCommentForm()
    if form.validate_on_submit():
        c = Comment(
            request_id=req.id,
            author_type="guest",
            author_guest_email=req.guest_email,
            visibility_scope="public",
            body=form.body.data.strip(),
        )
        db.session.add(c)
        _log(req, "comment_added", note="Guest added a public comment.", actor_label=req.guest_email)
        db.session.commit()
        flash("Comment added.", "success")
        return redirect(url_for("external.external_detail", token=token))

    return render_template(
        "external_detail.html",
        req=req,
        comments=public_comments,
        submissions=public_submissions,
        audit=public_audit,
        form=form,
        token=token,
    )


@external_bp.route("/<token>/reopen", methods=["POST"])
def external_reopen(token: str):
    req = _get_req_by_token(token)

    # Guests may reopen only when the request is in SENT_TO_A or CLOSED
    if req.status not in ("SENT_TO_A", "CLOSED"):
        flash("This request cannot be reopened from its current status.", "warning")
        return redirect(url_for("external.external_detail", token=token))

    old_status = req.status
    req.status = "B_IN_PROGRESS"
    req.owner_department = "B"

    _log(
        req,
        "status_change",
        note=f"Guest reopened request (was {old_status}).",
        from_status=old_status,
        to_status=req.status,
        actor_label=req.guest_email,
    )

    notify_users(
        users_in_department("B"),
        title=f"Request #{req.id} reopened by guest",
        body=req.title,
        url=url_for("requests.request_detail", request_id=req.id),
        ntype="status_change",
        request_id=req.id,
    )

    db.session.commit()
    flash("Request reopened and sent back to Dept B.", "success")
    return redirect(url_for("external.external_detail", token=token))