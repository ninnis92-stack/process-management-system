from datetime import datetime, timedelta
import time

from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import metrics as metrics_module
from ..extensions import db
from ..models import Request as ReqModel, SpecialEmailConfig
from ..notifcations import notify_users, users_in_department
from ..services.process_metrics import record_process_metric_event
from ..services.request_creation import (
    apply_submission_data_to_request,
    build_initial_artifact,
    create_form_submission,
    save_template_file_attachments,
)
from ..services.request_intake import (
    handle_template_prefill_request,
    load_request_template_context,
    validate_template_request_submission,
)
from .workflow import active_workflow_intake_preview
from . import requests_bp
from .forms import (
    NewRequestForm,
    CommentForm,
    ArtifactForm,
    TransitionForm,
    ToggleCReviewForm,
    RequestArtifactEditForm,
    DonorOnlyForm,
    AssignmentForm,
)
from .routes import _log


@requests_bp.route("/requests/new", methods=["GET", "POST"])
@login_required
def request_new():
    form = NewRequestForm()
    template_context = load_request_template_context("A")
    template = template_context.template
    template_fields = template_context.template_fields or None
    template_spec = template_context.template_spec
    template_sections = template_context.template_sections
    process_preview = active_workflow_intake_preview("A")

    if template and getattr(template, "external_enabled", False):
        if request.method == "POST":
            flash(
                "This form is provided by an external service; please submit via the external provider.",
                "warning",
            )
            return redirect(template.external_form_url or url_for("requests.request_new"))
        return render_template("request_external_form.html", template=template)

    if (template is None and form.validate_on_submit()) or (
        template is not None and request.method == "POST"
    ):
        comment_form = None
        artifact_form = None
        transition_form = None
        toggle_form = None
        request_edit_form = None
        donor_form = None
        assignment_form = None
        verification_results = {}
        applied_prefills = {}
        default_due = (
            form.due_at.data
            if getattr(form, "due_at", None) and form.due_at.data
            else (datetime.utcnow() + timedelta(days=2))
        )

        submission_data = {}
        if template is not None:
            validation_result = validate_template_request_submission(template_context)
            submission_data = validation_result.get("submission_data") or {}
            verification_results = validation_result.get("verification_results") or {}
            applied_prefills = validation_result.get("applied_prefills") or {}
            if not validation_result.get("ok"):
                flash(
                    validation_result.get("message")
                    or "Template submission could not be processed.",
                    "danger",
                )
                return render_template(
                    "request_new.html",
                    form=form,
                    template=template,
                    template_fields=template_fields,
                    template_spec=template_spec,
                    template_sections=template_sections,
                    process_preview=process_preview,
                )

        req = ReqModel(
            title=f"Dynamic request {int(time.time())}",
            request_type="both",
            pricebook_status="unknown",
            description="",
            priority="medium",
            requires_c_review=False,
            status="NEW_FROM_A",
            owner_department="B",
            submitter_type="user",
            created_by_user_id=current_user.id,
            due_at=default_due,
        )

        db.session.add(req)
        db.session.flush()
        if template is not None:
            apply_submission_data_to_request(req, submission_data)
            try:
                if comment_form is None:
                    comment_form = CommentForm()
            except Exception:
                comment_form = None
            try:
                if artifact_form is None:
                    artifact_form = ArtifactForm()
            except Exception:
                artifact_form = None
            try:
                if transition_form is None:
                    transition_form = TransitionForm()
            except Exception:
                transition_form = None
            try:
                if toggle_form is None:
                    toggle_form = ToggleCReviewForm()
            except Exception:
                toggle_form = None
            try:
                if request_edit_form is None:
                    request_edit_form = RequestArtifactEditForm()
            except Exception:
                request_edit_form = None
            try:
                if donor_form is None:
                    donor_form = DonorOnlyForm()
            except Exception:
                donor_form = None
            try:
                if assignment_form is None:
                    assignment_form = AssignmentForm()
            except Exception:
                assignment_form = None

        artifact = build_initial_artifact(
            req,
            form,
            submission_data if template is not None else None,
            current_user.id,
        )
        db.session.add(artifact)
        _log(
            req,
            "artifact_added",
            note=f"Initial artifact created at submission: {artifact.artifact_type}",
        )

        notify_users(
            users_in_department(req.owner_department),
            title=f"Request generated: #{req.id}",
            body=f"{req.title} — generated by {current_user.email}",
            url=url_for("requests.request_detail", request_id=req.id),
            ntype="request_generated",
            request_id=req.id,
        )

        db.session.commit()

        if template is not None:
            fs = create_form_submission(template, req, submission_data, current_user.id)
            save_template_file_attachments(fs, template_fields, current_user.id)

            if verification_results or applied_prefills:
                fs.data = dict(fs.data or {})
                if verification_results:
                    fs.data["_verifications"] = verification_results
                if applied_prefills:
                    fs.data["_auto_prefills"] = applied_prefills
                db.session.add(fs)
                db.session.commit()

                try:
                    cfg = SpecialEmailConfig.get()
                except Exception:
                    cfg = None

                if cfg and getattr(cfg, "request_form_auto_reject_oos_enabled", False):
                    blocking_failures = []
                    for field_name, result in verification_results.items():
                        if result.get("type") != "external_lookup":
                            continue
                        if result.get("ok") is not False:
                            continue
                        if result.get("value") in (None, ""):
                            continue
                        blocking_failures.append(
                            {
                                "field": field_name,
                                "provider": result.get("provider"),
                                "external_key": result.get("external_key"),
                                "details": result.get("details"),
                                "reason": result.get("reason"),
                                "value": result.get("value"),
                            }
                        )

                    if blocking_failures:
                        req.status = "CLOSED"
                        db.session.add(req)
                        _log(
                            req,
                            "auto_rejected_oos",
                            note=f"Auto-rejected after provider verification failure: {blocking_failures}",
                        )
                        db.session.commit()

                        try:
                            recipients = (
                                [req.created_by_user]
                                if req.created_by_user_id and req.created_by_user
                                else []
                            )
                            if recipients:
                                notify_users(
                                    recipients,
                                    title=f"Request auto-rejected #{req.id}",
                                    body=(
                                        cfg.request_form_inventory_out_of_stock_message
                                        or "Request was auto-rejected because one or more populated fields were not available in the connected source system."
                                    ),
                                    url=url_for("requests.request_detail", request_id=req.id),
                                    ntype="auto_reject",
                                    request_id=req.id,
                                )
                        except Exception:
                            current_app.logger.exception(
                                "Failed to send auto-reject notification"
                            )

                        flash(
                            cfg.request_form_inventory_out_of_stock_message
                            or "Request auto-rejected because a populated API-verified field was unavailable.",
                            "warning",
                        )
                        return redirect(url_for("requests.request_detail", request_id=req.id))

        try:
            metrics_module.requests_created_total.labels(dept=req.owner_department).inc()
            metrics_module.update_owner_gauge(db.session, ReqModel)
            record_process_metric_event(
                req,
                event_type="request_created",
                actor_user=current_user,
                actor_department=getattr(current_user, "department", None),
                to_status=req.status,
                metadata={"request_type": req.request_type, "priority": req.priority},
            )
        except Exception:
            current_app.logger.exception("Failed to update metrics on request creation")

        flash(f"Request #{req.id} submitted successfully.", "success")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    return render_template(
        "request_new.html",
        form=form,
        template=template,
        template_fields=template_fields,
        template_spec=template_spec,
        template_sections=template_sections,
        process_preview=process_preview,
    )


@requests_bp.route("/requests/template-prefill", methods=["POST"])
@login_required
def template_field_prefill():
    template_context = load_request_template_context("A")
    if not template_context.assigned:
        return jsonify({"ok": False, "error": "template_not_assigned"}), 404
    payload = request.get_json(silent=True) or {}
    response, status_code = handle_template_prefill_request(template_context, payload)
    return jsonify(response), status_code
