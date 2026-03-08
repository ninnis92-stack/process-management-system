from __future__ import annotations

from collections import defaultdict
from sqlalchemy import and_, or_
from datetime import datetime, timedelta
from typing import Any

from flask import current_app

from ..extensions import db
from ..models import (
    MetricsConfig,
    ProcessMetricEvent,
    Request as ReqModel,
    Submission,
    User,
    Artifact,
)


def get_range_cutoff(range_key: str) -> tuple[datetime, str]:
    now = datetime.utcnow()
    key = (range_key or "weekly").lower()
    if key == "daily":
        return datetime(now.year, now.month, now.day), "Daily (since today 00:00 UTC)"
    if key == "monthly":
        return datetime(now.year, now.month, 1), "Monthly (since start of month)"
    if key == "yearly":
        return datetime(now.year, 1, 1), "Yearly (since start of year)"
    if key == "all":
        # no cutoff; include every recorded event/request
        return datetime(1970, 1, 1), "All time"
    return (
        datetime(now.year, now.month, now.day) - timedelta(days=now.weekday()),
        "Weekly (since start of week)",
    )


def _event_is_enabled(cfg: MetricsConfig, event_type: str) -> bool:
    if not cfg or not cfg.enabled:
        return False
    if event_type == "request_created":
        return bool(cfg.track_request_created)
    if event_type == "assignment_changed":
        return bool(cfg.track_assignments)
    if event_type == "status_changed":
        return bool(cfg.track_status_changes)
    return True


def record_process_metric_event(
    req: ReqModel,
    *,
    event_type: str,
    actor_user: User | None = None,
    actor_department: str | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Persist a normalized analytics event without affecting core flow."""
    try:
        cfg = MetricsConfig.get()
    except Exception:
        return

    if not _event_is_enabled(cfg, event_type):
        return

    try:
        now = datetime.utcnow()
        prev = (
            ProcessMetricEvent.query.filter_by(request_id=req.id)
            .order_by(ProcessMetricEvent.created_at.desc(), ProcessMetricEvent.id.desc())
            .first()
        )
        since_last_event_seconds = None
        if prev and prev.created_at:
            since_last_event_seconds = max(
                int((now - prev.created_at).total_seconds()), 0
            )

        request_age_seconds = None
        if getattr(req, "created_at", None):
            request_age_seconds = max(int((now - req.created_at).total_seconds()), 0)

        evt = ProcessMetricEvent(
            request_id=req.id,
            actor_user_id=getattr(actor_user, "id", None),
            actor_department=(actor_department or getattr(actor_user, "department", None) or None),
            owner_department=getattr(req, "owner_department", None),
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            assigned_to_user_id=getattr(req, "assigned_to_user_id", None),
            since_last_event_seconds=since_last_event_seconds,
            request_age_seconds=request_age_seconds,
            metadata_json=metadata or {},
            created_at=now,
        )
        db.session.add(evt)
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        try:
            current_app.logger.exception("Failed to record process metric event")
        except Exception:
            pass


def build_process_metrics_summary(*, range_key: str = "weekly", depts: list[str] | None = None, query: str | None = None) -> dict[str, Any]:
    """Return a snapshot of metrics.

    ``query`` may be supplied to restrict the set of requests/event rows to
    those matching the same rules used by :func:`search_requests`.
    """
    now = datetime.utcnow()
    cutoff, label = get_range_cutoff(range_key)
    cfg = MetricsConfig.get()

    req_q = ReqModel.query
    evt_q = ProcessMetricEvent.query.filter(ProcessMetricEvent.created_at >= cutoff)
    if depts:
        req_q = req_q.filter(ReqModel.owner_department.in_(depts))
        evt_q = evt_q.filter(ProcessMetricEvent.owner_department.in_(depts))

    # apply optional textual search filter: mimic logic from search_requests
    filtered_ids: list[int] | None = None
    if query:
        q = query.strip()
        if q:
            filters = [
                ReqModel.title.ilike(f"%{q}%"),
                ReqModel.description.ilike(f"%{q}%"),
            ]
            filters.extend(
                [
                    Artifact.donor_part_number.ilike(f"%{q}%"),
                    Artifact.target_part_number.ilike(f"%{q}%"),
                    Artifact.instructions_url.ilike(f"%{q}%"),
                ]
            )
            filters.extend(
                [
                    Submission.summary.ilike(f"%{q}%"),
                    Submission.details.ilike(f"%{q}%"),
                    ReqModel.request_type.ilike(f"%{q}%"),
                    ReqModel.pricebook_status.ilike(f"%{q}%"),
                    ReqModel.sales_list_reference.ilike(f"%{q}%"),
                ]
            )

            qry = req_q.outerjoin(Artifact, Artifact.request_id == ReqModel.id)
            qry = qry.outerjoin(
                Submission,
                and_(
                    Submission.request_id == ReqModel.id,
                    Submission.is_public_to_submitter == True,
                ),
            )
            if q.isdigit():
                id_filter = ReqModel.id == int(q)
                qry = qry.filter(or_(id_filter, *filters))
            else:
                qry = qry.filter(or_(*filters))

            results = qry.all()
            filtered_ids = [r.id for r in results]
            req_q = req_q.filter(ReqModel.id.in_(filtered_ids))
            evt_q = evt_q.filter(ProcessMetricEvent.request_id.in_(filtered_ids))

    requests = req_q.all()
    events = evt_q.order_by(ProcessMetricEvent.created_at.desc()).all()

    totals = defaultdict(int)
    opens = defaultdict(int)
    created_window = defaultdict(int)
    closed_window = defaultdict(int)
    avg_completion_samples = defaultdict(list)
    within_target_counts = defaultdict(int)
    tracked_events = defaultdict(int)
    status_changes = defaultdict(int)
    assignments = defaultdict(int)
    slow_events = defaultdict(int)
    avg_gap_samples = defaultdict(list)

    target_seconds = max(int((cfg.target_completion_hours or 48) * 3600), 1)
    slow_seconds = max(int((cfg.slow_event_threshold_hours or 8) * 3600), 1)

    for req in requests:
        dept = req.owner_department or "?"
        totals[dept] += 1
        if req.status != "CLOSED":
            opens[dept] += 1
        if req.created_at and req.created_at >= cutoff:
            created_window[dept] += 1
        if req.status == "CLOSED" and req.updated_at and req.updated_at >= cutoff:
            closed_window[dept] += 1
            if req.created_at and req.updated_at:
                age_seconds = max(int((req.updated_at - req.created_at).total_seconds()), 0)
                avg_completion_samples[dept].append(age_seconds)
                if age_seconds <= target_seconds:
                    within_target_counts[dept] += 1

    user_rollup: dict[int, dict[str, Any]] = {}
    for evt in events:
        dept = evt.owner_department or "?"
        tracked_events[dept] += 1
        if evt.event_type == "status_changed":
            status_changes[dept] += 1
        if evt.event_type == "assignment_changed":
            assignments[dept] += 1
        if evt.since_last_event_seconds is not None:
            avg_gap_samples[dept].append(evt.since_last_event_seconds)
            if evt.since_last_event_seconds >= slow_seconds:
                slow_events[dept] += 1

        if evt.actor_user_id:
            row = user_rollup.get(evt.actor_user_id)
            if row is None:
                actor = db.session.get(User, evt.actor_user_id)
                row = {
                    "user_id": evt.actor_user_id,
                    "email": getattr(actor, "email", f"User #{evt.actor_user_id}"),
                    "department": evt.actor_department or getattr(actor, "department", None),
                    "events": 0,
                    "status_changes": 0,
                    "assignments": 0,
                    "slow_events": 0,
                    "avg_gap_samples": [],
                    "completion_samples": [],
                    "closed_count": 0,
                }
                user_rollup[evt.actor_user_id] = row
            row["events"] += 1
            if evt.event_type == "status_changed":
                row["status_changes"] += 1
            if evt.event_type == "assignment_changed":
                row["assignments"] += 1
            if evt.since_last_event_seconds is not None:
                row["avg_gap_samples"].append(evt.since_last_event_seconds)
                if evt.since_last_event_seconds >= slow_seconds:
                    row["slow_events"] += 1
            if evt.to_status == "CLOSED" and evt.request_age_seconds is not None:
                row["completion_samples"].append(evt.request_age_seconds)
                row["closed_count"] += 1

    departments = depts or ["A", "B", "C"]
    by_dept = []
    for dept in departments:
        closed = closed_window.get(dept, 0)
        completion_avg = avg_completion_samples.get(dept, [])
        gap_avg = avg_gap_samples.get(dept, [])
        by_dept.append(
            {
                "dept": dept,
                "total": totals.get(dept, 0),
                "open": opens.get(dept, 0),
                "created_window": created_window.get(dept, 0),
                "closed_window": closed,
                "tracked_events": tracked_events.get(dept, 0),
                "status_changes": status_changes.get(dept, 0),
                "assignments": assignments.get(dept, 0),
                "slow_events": slow_events.get(dept, 0),
                "avg_completion_hours": round(sum(completion_avg) / len(completion_avg) / 3600, 2)
                if completion_avg
                else None,
                "avg_gap_hours": round(sum(gap_avg) / len(gap_avg) / 3600, 2) if gap_avg else None,
                "within_target_pct": round((within_target_counts.get(dept, 0) / closed) * 100, 1)
                if closed
                else None,
            }
        )

    users = []
    for row in user_rollup.values():
        gap_avg = row["avg_gap_samples"]
        completion_avg = row["completion_samples"]
        users.append(
            {
                "user_id": row["user_id"],
                "email": row["email"],
                "department": row["department"],
                "events": row["events"],
                "status_changes": row["status_changes"],
                "assignments": row["assignments"],
                "slow_events": row["slow_events"],
                "avg_gap_hours": round(sum(gap_avg) / len(gap_avg) / 3600, 2) if gap_avg else None,
                "avg_completion_hours": round(sum(completion_avg) / len(completion_avg) / 3600, 2)
                if completion_avg
                else None,
                "closed_count": row["closed_count"],
            }
        )
    users.sort(key=lambda item: (-item["events"], item["email"] or ""))
    users = users[: max(int(cfg.user_metrics_limit or 15), 1)]

    interactions = []
    try:
        interaction_query = Submission.query.filter(Submission.created_at >= cutoff)
        if depts:
            interaction_query = interaction_query.filter(
                (Submission.from_department.in_(depts))
                | (Submission.to_department.in_(depts))
            )
        rows = (
            interaction_query.with_entities(
                Submission.from_department,
                Submission.to_department,
                db.func.count(Submission.id),
            )
            .group_by(Submission.from_department, Submission.to_department)
            .order_by(db.func.count(Submission.id).desc())
            .all()
        )
        interactions = [
            {
                "from_department": from_dept or "—",
                "to_department": to_dept or "—",
                "count": count,
            }
            for from_dept, to_dept, count in rows
        ]
    except Exception:
        interactions = []

    return {
        "now": now,
        "cutoff": cutoff,
        "range_key": range_key,
        "range_label": label,
        "config": cfg,
        "summary": {
            "tracked_events_total": len(events),
            "tracked_requests_total": len({evt.request_id for evt in events}),
            "active_users_total": len(user_rollup),
        },
        "by_dept": by_dept,
        "users": users,
        "interactions": interactions,
    }
