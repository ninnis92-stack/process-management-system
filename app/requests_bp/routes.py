import os
import uuid
from flask import Blueprint, render_template, redirect, request, url_for, flash, abort, send_***REMOVED***le, current_app
from flask_login import login_required, current_user
from flask_wtf import form
from werkzeug.utils import secure_***REMOVED***lename

from ..extensions import db
from ..models import Request as ReqModel, Comment, AuditLog, Artifact, Submission, Attachment
from .forms import NewRequestForm, CommentForm, ArtifactForm, TransitionForm, ToggleCReviewForm, RequestArtifactEditForm, DonorOnlyForm
from .permissions import can_view_request, visible_comment_scopes_for_user, allowed_comment_scopes_for_user
from .workflow import transition_allowed, owner_for_status, handoff_for_transition

requests_bp = Blueprint("requests", __name__, url_pre***REMOVED***x="")

def _has_part_number_artifact(req: ReqModel) -> bool:
    return any(a.artifact_type == "part_number" for a in req.artifacts)

def can_add_artifact(req: ReqModel, dept: str, artifact_type: str) -> bool:
    # Dept B: only part_number
    if dept == "B":
        return artifact_type in ("part_number", "instructions")

    # Dept A: can add any artifact type
    if dept == "A":
        return artifact_type in ("part_number", "instructions")

    # Dept C: can add ONLY part_number, ONLY when in review, ONLY if none exist yet
    if dept == "C":
        if artifact_type != "part_number":
            return False
        if req.status != "PENDING_C_REVIEW":
            return False
        if _has_part_number_artifact(req):
            return False
        return True

    return False

def can_edit_artifact(req: ReqModel, artifact: Artifact, dept: str) -> bool:
    # Dept B: can edit only part_number artifacts
    if dept == "B":
        return artifact.artifact_type == "part_number"

    # Dept A: can edit only when edit_requested is True
    if dept == "A":
        return artifact.edit_requested is True

    # Dept C: no edits (only add if missing PN while in review)
    return False

def _log(req, action_type, note=None, from_status=None, to_status=None, actor_type="user"):
    entry = AuditLog(
        request_id=req.id,
        actor_type=actor_type,
        actor_user_id=current_user.id if actor_type == "user" else None,
        actor_label=current_user.email if actor_type == "user" else actor_type,
        action_type=action_type,
        from_status=from_status,
        to_status=to_status,
        note=note,
    )
    db.session.add(entry)

def is_transition_valid_for_request(req: ReqModel, dept: str, from_status: str, to_status: str) -> bool:
    if not transition_allowed(dept, from_status, to_status):
        return False
    # If C review is required: block bypass
    if req.requires_c_review and from_status == "B_IN_PROGRESS" and to_status == "B_FINAL_REVIEW":
        return False
    # If C review is NOT required: block sending to C
    if (not req.requires_c_review) and from_status == "B_IN_PROGRESS" and to_status == "PENDING_C_REVIEW":
        return False
    return True

@requests_bp.route("/")
def root():
    return redirect(url_for("requests.dashboard"))

@requests_bp.route("/dashboard")
@login_required
def dashboard():
    dept = current_user.department
    if dept == "A":
        my_reqs = ReqModel.query.***REMOVED***lter_by(created_by_user_id=current_user.id).order_by(ReqModel.updated_at.desc()).all()
        return render_template("dashboard.html", mode="A", requests=my_reqs)
    if dept == "B":
        buckets = {
            "New from A": ReqModel.query.***REMOVED***lter(ReqModel.owner_department=="B", ReqModel.status=="NEW_FROM_A").order_by(ReqModel.updated_at.desc()).all(),
            "In B Review": ReqModel.query.***REMOVED***lter(ReqModel.owner_department=="B", ReqModel.status=="B_IN_PROGRESS").order_by(ReqModel.updated_at.desc()).all(),
            "Needs changes": ReqModel.query.***REMOVED***lter(ReqModel.owner_department=="B", ReqModel.status=="C_NEEDS_CHANGES").order_by(ReqModel.updated_at.desc()).all(),
            "Approved by C": ReqModel.query.***REMOVED***lter(ReqModel.owner_department=="B", ReqModel.status=="C_APPROVED").order_by(ReqModel.updated_at.desc()).all(),
            "Final review": ReqModel.query.***REMOVED***lter(ReqModel.owner_department=="B", ReqModel.status=="B_FINAL_REVIEW").order_by(ReqModel.updated_at.desc()).all(),
            "Sent to A": ReqModel.query.***REMOVED***lter(ReqModel.owner_department=="B", ReqModel.status=="SENT_TO_A").order_by(ReqModel.updated_at.desc()).all(),
        }
        return render_template("dashboard.html", mode="B", buckets=buckets)
    if dept == "C":
        pending = ReqModel.query.***REMOVED***lter_by(status="PENDING_C_REVIEW").order_by(ReqModel.updated_at.desc()).all()
        return render_template("dashboard.html", mode="C", requests=pending)
    abort(403)

@requests_bp.route("/requests/new", methods=["GET", "POST"])
@login_required
def request_new():
    form = NewRequestForm()

    is_valid = form.validate_on_submit()
    # TEMP DEBUG (remove after it works)
    if request.method == "POST":
        print("VALID:", is_valid)
        print("ERRORS:", form.errors)
        print("DUE_AT:", getattr(form, "due_at", None).data if hasattr(form, "due_at") else "NO FIELD")

    if is_valid:
        req = ReqModel(
            title=form.title.data.strip(),
            request_type=form.request_type.data,
            pricebook_status=form.pricebook_status.data,
            description=form.description.data.strip(),
            priority=form.priority.data,
            requires_c_review=form.requires_c_review.data,
            status="NEW_FROM_A",
            owner_department="B",
            submitter_type="user",
            created_by_user_id=current_user.id,
            due_at=form.due_at.data,  # ✅ REQUIRED
        )

        db.session.add(req)
        db.session.flush()  # ✅ so req.id exists

        # ✅ Auto-create initial artifact from Dept A submission
        # Decide artifact_type based on request_type
        initial_artifact_type = "part_number" if form.request_type.data == "part_number" else "instructions"

        a = Artifact(
            request_id=req.id,
            artifact_type=initial_artifact_type,

            donor_part_number=(form.donor_part_number.data or "").strip() or None,
            target_part_number=(form.target_part_number.data or "").strip() or None,
            no_donor_reason=(form.no_donor_reason.data or "").strip() or None,

            created_by_user_id=current_user.id,
            created_by_department="A",
        )

        db.session.add(a)

        # (Optional but helpful) log it
        _log(req, "artifact_added", note=f"Initial artifact created at submission: {a.artifact_type}")

        db.session.commit()

        flash(f"Request #{req.id} submitted successfully.", "success")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    return render_template("request_new.html", form=form)

@requests_bp.route("/requests/<int:request_id>")
@login_required
def request_detail(request_id: int):
    req = ReqModel.query.get_or_404(request_id)
    if not can_view_request(req):
        abort(403)

    # Comments ***REMOVED***ltering
    allowed_scopes = visible_comment_scopes_for_user()
    comments = Comment.query.***REMOVED***lter_by(request_id=req.id).order_by(Comment.created_at.asc()).all()
    comments = [c for c in comments if c.visibility_scope in allowed_scopes]

    comment_form = CommentForm()
    comment_form.visibility_scope.choices = [(s, s.replace("_", " ").title()) for s in allowed_comment_scopes_for_user()]

    artifact_form = ArtifactForm()

    transition_form = TransitionForm()
    dept = current_user.department
    possible = []
    for to in ("B_IN_PROGRESS","PENDING_C_REVIEW","C_APPROVED","C_NEEDS_CHANGES","B_FINAL_REVIEW","SENT_TO_A","CLOSED"):
        if is_transition_valid_for_request(req, dept, req.status, to):
            possible.append((to, to.replace("_"," ").title()))
    transition_form.to_status.choices = possible

    toggle_form = ToggleCReviewForm()

    request_edit_form = RequestArtifactEditForm()

    donor_form = DonorOnlyForm()

    submissions = Submission.query.***REMOVED***lter_by(request_id=req.id).order_by(Submission.created_at.asc()).all()
    audit = AuditLog.query.***REMOVED***lter_by(request_id=req.id).order_by(AuditLog.created_at.asc()).all()

    has_part_number = any(a.artifact_type == "part_number" for a in req.artifacts)
    has_instructions = any(a.artifact_type == "instructions" for a in req.artifacts)
    return render_template(
        "request_detail.html",
        req=req,
        comments=comments,
        submissions=submissions,
        audit=audit,
        comment_form=comment_form,
        artifact_form=artifact_form,
        transition_form=transition_form,
        toggle_form=toggle_form,
        request_edit_form = request_edit_form,
        donor_form=donor_form,
        has_part_number=has_part_number,
        has_instructions=has_instructions,
    )

@requests_bp.route("/requests/<int:request_id>/comment", methods=["POST"])
@login_required
def add_comment(request_id: int):
    req = ReqModel.query.get_or_404(request_id)
    if not can_view_request(req):
        abort(403)

    form = CommentForm()
    form.visibility_scope.choices = [(s, s) for s in allowed_comment_scopes_for_user()]
    existing_types = {a.artifact_type for a in req.artifacts}
    if form.artifact_type.data in existing_types:
        flash("That artifact type already exists for this request. Please edit the existing one.", "warning")
        return redirect(url_for("requests.request_detail", request_id=req.id))
    if form.validate_on_submit():
        c = Comment(
            request_id=req.id,
            author_type="user",
            author_user_id=current_user.id,
            visibility_scope=form.visibility_scope.data,
            body=form.body.data.strip(),
        )
        db.session.add(c)
        _log(req, "comment_added", note=f"Comment added ({c.visibility_scope}).")
        db.session.commit()
        flash("Comment added.", "success")
    else:
        flash("Comment failed validation.", "danger")
    return redirect(url_for("requests.request_detail", request_id=req.id))

@requests_bp.route("/requests/<int:request_id>/artifact", methods=["POST"])
@login_required
def add_artifact(request_id: int):
    req = ReqModel.query.get_or_404(request_id)
    if not can_view_request(req):
        abort(403)

    form = ArtifactForm()  # ✅ de***REMOVED***ne form BEFORE using it
    dept = current_user.department

    # ✅ permission check must happen after form exists
    if not can_add_artifact(req, dept, form.artifact_type.data):
        abort(403)

    if form.validate_on_submit():
        a = Artifact(
            request_id=req.id,
            artifact_type=form.artifact_type.data,

            donor_part_number=(form.donor_part_number.data or "").strip() or None,
            target_part_number=(form.target_part_number.data or "").strip() or None,
            no_donor_reason=(form.no_donor_reason.data or "").strip() or None,
            instructions_url=(form.instructions_url.data or "").strip() or None,

            created_by_user_id=current_user.id,
            created_by_department=current_user.department,
        )

        db.session.add(a)
        _log(
            req,
            "artifact_updated",
            note=f"Artifact added: {a.artifact_type} (donor={a.donor_part_number}, target={a.target_part_number}).",
        )
        db.session.commit()
        flash("Artifact added.", "success")
    else:
        flash("Artifact failed validation.", "danger")

    return redirect(url_for("requests.request_detail", request_id=req.id))

def _validate_***REMOVED***les(***REMOVED***les) -> list:
    cfg = current_app.con***REMOVED***g
    cleaned = []
    if not ***REMOVED***les:
        return cleaned
    if len(***REMOVED***les) > cfg["MAX_FILES_PER_SUBMISSION"]:
        raise ValueError(f"Too many ***REMOVED***les (max {cfg['MAX_FILES_PER_SUBMISSION']}).")
    for f in ***REMOVED***les:
        if not f or not f.***REMOVED***lename:
            continue
        if f.mimetype not in cfg["ALLOWED_IMAGE_MIMES"]:
            raise ValueError("Only PNG/JPEG/WebP images are allowed.")
        pos = f.stream.tell()
        f.stream.seek(0, os.SEEK_END)
        size = f.stream.tell()
        f.stream.seek(pos)
        if size > cfg["MAX_FILE_SIZE_BYTES"]:
            raise ValueError("One of the images exceeds 10MB.")
        cleaned.append((f, size))
    return cleaned

@requests_bp.route("/requests/<int:request_id>/transition", methods=["POST"])
@login_required
def do_transition(request_id: int):
    req = ReqModel.query.get_or_404(request_id)
    if not can_view_request(req):
        abort(403)

    form = TransitionForm()
    dept = current_user.department

    possible = []
    for to in ("B_IN_PROGRESS","PENDING_C_REVIEW","C_APPROVED","C_NEEDS_CHANGES","B_FINAL_REVIEW","SENT_TO_A","CLOSED"):
        if is_transition_valid_for_request(req, dept, req.status, to):
            possible.append((to, to))
    form.to_status.choices = possible

    if not form.validate_on_submit():
        flash("Transition failed validation.", "danger")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    to_status = form.to_status.data
    if not is_transition_valid_for_request(req, dept, req.status, to_status):
        abort(403)

    # If this transition is a handoff, require submission + attachments optional
    handoff = handoff_for_transition(req.status, to_status)
    if handoff:
        if not form.submission_summary.data or not form.submission_details.data:
            flash("Submission Summary and Details are required for this handoff.", "danger")
            return redirect(url_for("requests.request_detail", request_id=req.id))

        try:
            validated = _validate_***REMOVED***les(form.***REMOVED***les.data)
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(url_for("requests.request_detail", request_id=req.id))

        from_dept, to_dept = handoff
        is_public = (to_dept == "A") or (from_dept == "A")
        sub = Submission(
            request_id=req.id,
            from_department=from_dept,
            to_department=to_dept,
            from_status=req.status,
            to_status=to_status,
            summary=form.submission_summary.data.strip(),
            details=form.submission_details.data.strip(),
            is_public_to_submitter=is_public,
            created_by_user_id=current_user.id,
        )
        db.session.add(sub)
        db.session.flush()

        for f, size in validated:
            orig = secure_***REMOVED***lename(f.***REMOVED***lename)
            stored = f"{uuid.uuid4().hex}_{orig}"
            save_path = os.path.join(current_app.con***REMOVED***g["UPLOAD_FOLDER"], stored)
            f.save(save_path)
            att = Attachment(
                submission_id=sub.id,
                uploaded_by_user_id=current_user.id,
                original_***REMOVED***lename=orig,
                stored_***REMOVED***lename=stored,
                content_type=f.mimetype,
                size_bytes=size,
            )
            db.session.add(att)

        _log(req, "submission_created", note=f"Submission packet created ({from_dept}→{to_dept}).")

    from_status = req.status
    req.status = to_status
    req.owner_department = owner_for_status(to_status)

    _log(req, "status_change", note=f"Status changed by Dept {dept}.", from_status=from_status, to_status=to_status)

    db.session.commit()
    flash(f"Moved to {to_status}.", "success")
    return redirect(url_for("requests.request_detail", request_id=req.id))

@requests_bp.route("/requests/<int:request_id>/toggle_c_review", methods=["POST"])
@login_required
def toggle_c_review(request_id: int):
    req = ReqModel.query.get_or_404(request_id)

    if current_user.department != "B":
        abort(403)
    if not can_view_request(req):
        abort(403)

    if req.status not in ("NEW_FROM_A", "B_IN_PROGRESS"):
        flash("C review can only be toggled while the request is NEW_FROM_A or B_IN_PROGRESS.", "danger")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    form = ToggleCReviewForm()
    if not form.validate_on_submit():
        flash("Reason is required to toggle C review.", "danger")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    old_value = req.requires_c_review
    req.requires_c_review = not req.requires_c_review

    note = (
        f"Dept B toggled requires_c_review: {old_value} → {req.requires_c_review}\n"
        f"Reason:\n{form.reason.data.strip()}"
    )
    _log(req, "c_review_toggled", note=note)
    db.session.commit()

    flash(f"Requires Dept C Review set to: {req.requires_c_review}", "success")
    return redirect(url_for("requests.request_detail", request_id=req.id))

@requests_bp.route("/attachments/<int:attachment_id>")
@login_required
def download_attachment(attachment_id: int):
    att = Attachment.query.get_or_404(attachment_id)
    sub = att.submission
    req = sub.request

    if not can_view_request(req):
        abort(403)

    ***REMOVED***le_path = os.path.join(current_app.con***REMOVED***g["UPLOAD_FOLDER"], att.stored_***REMOVED***lename)
    if not os.path.exists(***REMOVED***le_path):
        abort(404)

    return send_***REMOVED***le(***REMOVED***le_path, mimetype=att.content_type, as_attachment=False, download_name=att.original_***REMOVED***lename)

@requests_bp.route("/artifacts/<int:artifact_id>/request_edit", methods=["POST"])
@login_required
def request_artifact_edit(artifact_id: int):
    artifact = Artifact.query.get_or_404(artifact_id)
    req = artifact.request

    if not can_view_request(req):
        abort(403)
    if current_user.department != "B":
        abort(403)

    form = RequestArtifactEditForm()
    if not form.validate_on_submit():
        flash("Edit request note is required.", "danger")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    artifact.edit_requested = True
    artifact.edit_requested_note = form.note.data.strip()

    _log(req, "assignment_changed", note=f"Dept B requested Dept A edit on artifact #{artifact.id}.\nNote:\n{artifact.edit_requested_note}")
    db.session.commit()

    flash("Edit request sent to Dept A (artifact unlocked for A editing).", "success")
    return redirect(url_for("requests.request_detail", request_id=req.id))

@requests_bp.route("/artifacts/<int:artifact_id>/edit", methods=["POST"])
@login_required
def edit_artifact(artifact_id: int):
    artifact = Artifact.query.get_or_404(artifact_id)
    req = artifact.request

    if not can_view_request(req):
        abort(403)

    dept = current_user.department
    if not can_edit_artifact(req, artifact, dept):
        abort(403)

    form = ArtifactForm()
    if not form.validate_on_submit():
        flash("Artifact failed validation.", "danger")
        return redirect(...)

    if not can_add_artifact(req, dept, form.artifact_type.data):
        abort(403)

    # then create artifact...
    
    # Enforce: B can only edit part_number (already checked),
    # A edit only allowed when requested (already checked),
    # and A should NOT change artifact type (keep it stable).
    if form.artifact_type.data != artifact.artifact_type:
        flash("Artifact type cannot be changed.", "danger")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    artifact.donor_part_number = (form.donor_part_number.data or "").strip() or None
    artifact.target_part_number = (form.target_part_number.data or "").strip() or None
    artifact.no_donor_reason = (form.no_donor_reason.data or "").strip() or None
    artifact.instructions_url = (form.instructions_url.data or "").strip() or None

    # If Dept A edits, clear the edit request flag (so it’s “locked” again)
    if dept == "A":
        artifact.edit_requested = False
        artifact.edit_requested_note = None

    _log(req, "artifact_updated", note=f"Artifact #{artifact.id} updated by Dept {dept}.")
    db.session.commit()
    flash("Artifact updated.", "success")
    return redirect(url_for("requests.request_detail", request_id=req.id))

@requests_bp.route("/artifacts/<int:artifact_id>/set_donor", methods=["POST"])
@login_required
def set_artifact_donor(artifact_id: int):
    artifact = Artifact.query.get_or_404(artifact_id)
    req = artifact.request

    if not can_view_request(req):
        abort(403)

    if current_user.department != "B":
        abort(403)

    if artifact.artifact_type != "part_number":
        abort(403)

    form = DonorOnlyForm()
    if not form.validate_on_submit():
        flash("Donor part number is required.", "danger")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    artifact.donor_part_number = form.donor_part_number.data.strip()
    artifact.no_donor_reason = None  # Clear reason if donor is added

    _log(req, "artifact_added",
         note=f"Dept B updated donor part number on artifact #{artifact.id}.")
    db.session.commit()

    flash("Donor part number updated.", "success")
    return redirect(url_for("requests.request_detail", request_id=req.id))