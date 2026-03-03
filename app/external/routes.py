from flask import Blueprint, render_template, redirect, url_for, flash, abort
from ..extensions import db
from ..models import Artifact, Request as ReqModel, Comment, AuditLog, Submission
from .forms import ExternalNewRequestForm, ExternalCommentForm

external_bp = Blueprint("external", __name__, url_pre***REMOVED***x="/external")

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

@external_bp.route("/new", methods=["GET", "POST"])
def external_new():
    form = ExternalNewRequestForm()
    if form.validate_on_submit():
        req = ReqModel(
            title=form.title.data.strip(),
            request_type=form.request_type.data,
            description=form.description.data.strip(),
            priority=form.priority.data,
            requires_c_review=form.requires_c_review.data,
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
            details=req.description,
            is_public_to_submitter=True,
            created_by_guest_email=req.guest_email,
        )
        db.session.add(sub)
        _log(req, "submission_created", note="Initial submission packet created (Guest A→B).", actor_label=req.guest_email)

        db.session.commit()
        flash(f"Request #{req.id} submitted successfully. You can use this page to track updates.", "success")
        return redirect(url_for("external.external_detail", token=req.guest_access_token))

    return render_template("external_new.html", form=form)

def _get_req_by_token(token: str) -> ReqModel:
    req = ReqModel.query.***REMOVED***lter_by(guest_access_token=token).***REMOVED***rst()
    if not req:
        abort(404)
    return req

@external_bp.route("/<token>", methods=["GET", "POST"])
def external_detail(token: str):
    req = _get_req_by_token(token)

    public_comments = Comment.query.***REMOVED***lter_by(request_id=req.id, visibility_scope="public").order_by(Comment.created_at.asc()).all()
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