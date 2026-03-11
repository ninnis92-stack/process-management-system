from typing import Optional, Tuple

from ..models import StatusOption, Workflow

OWNER_BY_STATUS = {
    "PENDING_C_REVIEW": "C",
    "SENT_TO_A": "A",
}
DEFAULT_OWNER = "B"


def owner_for_status(status: str) -> str:
    # Prefer admin-configured StatusOption.target_department when present.
    try:
        opt = StatusOption.query.filter_by(code=status).first()
        if opt and opt.target_department:
            return opt.target_department
    except Exception:
        # If DB unavailable or misconfigured, fall back to hardcoded mapping.
        pass

    if status == "CLOSED":
        return "B"
    return OWNER_BY_STATUS.get(status, DEFAULT_OWNER)


ALLOWED_TRANSITIONS = {
    "A": {
        ("SENT_TO_A", "B_IN_PROGRESS"),  # Reopen to Dept B
        ("SENT_TO_A", "CLOSED"),  # Approve/close
        ("CLOSED", "B_IN_PROGRESS"),  # Reopen after close
    },
    "B": {
        ("NEW_FROM_A", "B_IN_PROGRESS"),
        ("NEW_FROM_A", "UNDER_REVIEW"),
        ("NEW_FROM_A", "PENDING_C_REVIEW"),
        ("NEW_FROM_A", "B_FINAL_REVIEW"),
        ("NEW_FROM_A", "CLOSED"),
        ("B_IN_PROGRESS", "PENDING_C_REVIEW"),
        ("B_IN_PROGRESS", "UNDER_REVIEW"),
        ("B_IN_PROGRESS", "WAITING_ON_A_RESPONSE"),
        (
            "B_IN_PROGRESS",
            "B_FINAL_REVIEW",
        ),  # bypass C (only if requires_c_review == False)
        ("WAITING_ON_A_RESPONSE", "B_IN_PROGRESS"),
        ("C_NEEDS_CHANGES", "B_IN_PROGRESS"),
        ("C_APPROVED", "B_FINAL_REVIEW"),
        ("C_APPROVED", "UNDER_REVIEW"),
        ("UNDER_REVIEW", "B_IN_PROGRESS"),
        ("UNDER_REVIEW", "B_FINAL_REVIEW"),
        ("UNDER_REVIEW", "SENT_TO_A"),
        ("UNDER_REVIEW", "CLOSED"),
        ("B_FINAL_REVIEW", "EXEC_APPROVAL"),
        ("B_FINAL_REVIEW", "SENT_TO_A"),
        ("EXEC_APPROVAL", "B_FINAL_REVIEW"),
        ("EXEC_APPROVAL", "SENT_TO_A"),
        ("SENT_TO_A", "CLOSED"),
    },
    "C": {
        ("PENDING_C_REVIEW", "C_APPROVED"),
        ("PENDING_C_REVIEW", "C_NEEDS_CHANGES"),
    },
}

HANDOFF_TRANSITIONS = {
    ("B_IN_PROGRESS", "PENDING_C_REVIEW"),  # B -> C
    ("PENDING_C_REVIEW", "C_APPROVED"),  # C -> B
    ("PENDING_C_REVIEW", "C_NEEDS_CHANGES"),  # C -> B
    ("B_FINAL_REVIEW", "SENT_TO_A"),  # B -> A/submitter
    ("EXEC_APPROVAL", "SENT_TO_A"),  # B -> A/submitter after exec signoff
    ("NEW_FROM_A", "PENDING_C_REVIEW"),  # B -> C (early send)
}


def _allowed_from_spec(spec: dict) -> set:
    """Return a set of (from,to) tuples from a workflow spec dict.

    Expected spec format (flexible):
      {"transitions": [{"from": "A", "to": "B"}, ...]}
    """
    out = set()
    if not spec or not isinstance(spec, dict):
        return out
    trans = spec.get("transitions") or spec.get("allowed_transitions") or []
    if isinstance(trans, dict):
        # support mapping format {"A": ["B","C"]}
        for k, vals in trans.items():
            if isinstance(vals, (list, tuple)):
                for v in vals:
                    out.add((k, v))
    elif isinstance(trans, (list, tuple)):
        for item in trans:
            if isinstance(item, dict):
                f = item.get("from") or item.get("source")
                t = item.get("to") or item.get("target")
                if f and t:
                    out.add((f, t))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                out.add((item[0], item[1]))
    return out


def _transition_entries_from_spec(spec: dict) -> list[dict]:
    entries = []
    if not spec or not isinstance(spec, dict):
        return entries

    trans = spec.get("transitions") or spec.get("allowed_transitions") or []
    if isinstance(trans, dict):
        for source, targets in trans.items():
            if not isinstance(targets, (list, tuple)):
                continue
            for target in targets:
                entries.append({"from": source, "to": target})
        return entries

    if not isinstance(trans, (list, tuple)):
        return entries

    for item in trans:
        if isinstance(item, dict):
            source = item.get("from") or item.get("source") or item.get("from_status")
            target = item.get("to") or item.get("target") or item.get("to_status")
            if source and target:
                entries.append(
                    {
                        "from": source,
                        "to": target,
                        "from_dept": item.get("from_dept")
                        or item.get("from_department"),
                        "to_dept": item.get("to_dept") or item.get("to_department"),
                    }
                )
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            entries.append({"from": item[0], "to": item[1]})
    return entries


def _normalize_route_department(value: Optional[str]) -> Optional[str]:
    raw = (value or "").strip().upper()
    return raw if raw in {"A", "B", "C"} else None


def workflow_scope_summary(workflow) -> str:
    dept = _normalize_route_department(getattr(workflow, "department_code", None))
    return f"Department {dept} only" if dept else "All departments"


def workflow_step_summary(
    step: dict, fallback_department: Optional[str] = None
) -> dict:
    code = (
        step.get("status")
        or step.get("code")
        or step.get("id")
        or step.get("name")
        or ""
    )
    label = step.get("label") or step.get("title") or code.replace("_", " ").title()
    from_department = _normalize_route_department(
        step.get("from_dept") or step.get("from_department")
    ) or _normalize_route_department(fallback_department)
    to_department = (
        _normalize_route_department(step.get("to_dept") or step.get("to_department"))
        or _normalize_route_department(fallback_department)
        or owner_for_status(code)
    )
    return {
        "status": code,
        "label": label,
        "from_department": from_department,
        "to_department": to_department,
        "summary": (
            f"{label} ({code})"
            if code and label != code
            else (label or code or "Unconfigured step")
        ),
    }


def workflow_editor_sections(
    spec: Optional[dict], fallback_department: Optional[str] = None
) -> list[dict]:
    steps = []
    if isinstance(spec, dict):
        steps = spec.get("steps") or []
    sections = [
        {
            "key": "basics",
            "title": "Basics",
            "summary": "Name the process flow, choose its scope, and decide whether it is live.",
        },
        {
            "key": "path",
            "title": "Process path",
            "summary": "Map the status sequence and department handoffs in the order users will follow.",
        },
        {
            "key": "implementation",
            "title": "Implementation",
            "summary": "Save a draft first, then implement status options when the process flow is ready for production.",
        },
    ]
    if steps:
        sections[1]["badge"] = f"{len(steps)} step{'s' if len(steps) != 1 else ''}"
    return sections


def workflow_intake_preview(
    workflow, fallback_department: Optional[str] = None, max_steps: int = 4
) -> dict:
    if not workflow:
        default_department = _normalize_route_department(fallback_department)
        return {
            "name": "Default process flow",
            "scope": (
                f"Starts in Department {default_department}"
                if default_department
                else "Default routing"
            ),
            "description": "Requests follow the standard status path configured for this department.",
            "steps": [],
            "has_multiple_routes": False,
            "route_count": 0,
        }

    spec = workflow.spec if isinstance(getattr(workflow, "spec", None), dict) else {}
    raw_steps = spec.get("steps") or []
    step_summaries = []
    for raw_step in raw_steps[:max_steps]:
        if isinstance(raw_step, dict):
            step_summaries.append(
                workflow_step_summary(
                    raw_step,
                    getattr(workflow, "department_code", None) or fallback_department,
                )
            )
        elif isinstance(raw_step, str):
            step_summaries.append(
                workflow_step_summary(
                    {"status": raw_step},
                    getattr(workflow, "department_code", None) or fallback_department,
                )
            )

    routes = _transition_entries_from_spec(spec)
    route_count = len(routes)
    unique_targets = {
        (
            _normalize_route_department(route.get("from_dept")),
            _normalize_route_department(route.get("to_dept")),
            route.get("to"),
        )
        for route in routes
    }
    has_multiple_routes = (
        len(unique_targets) != len({route.get("to") for route in routes})
        if routes
        else False
    )
    return {
        "name": getattr(workflow, "name", None) or "Default process flow",
        "scope": workflow_scope_summary(workflow),
        "description": getattr(workflow, "description", None)
        or "Requests follow this process flow after submission.",
        "steps": step_summaries,
        "has_multiple_routes": has_multiple_routes,
        "route_count": route_count,
    }


def active_workflow_intake_preview(dept: str, max_steps: int = 4) -> dict:
    workflow = _active_workflow_for_department(dept)
    return workflow_intake_preview(workflow, dept, max_steps=max_steps)


def _active_workflow_for_department(dept: str):
    wf = Workflow.query.filter_by(active=True, department_code=dept).first()
    if not wf:
        wf = Workflow.query.filter_by(active=True, department_code=None).first()
    return wf


def _inactive_workflow_for_department(dept: str):
    wf = Workflow.query.filter_by(active=False, department_code=dept).first()
    if not wf:
        wf = Workflow.query.filter_by(active=False, department_code=None).first()
    return wf


def _status_label_map_from_workflow(wf) -> dict:
    label_map = {}
    try:
        if wf and isinstance(wf.spec, dict):
            steps = wf.spec.get("steps") or wf.spec.get("labels")
            if isinstance(steps, dict):
                label_map.update(steps)
            elif isinstance(steps, (list, tuple)):
                for step in steps:
                    if not isinstance(step, dict):
                        continue
                    code = (
                        step.get("code")
                        or step.get("id")
                        or step.get("status")
                        or step.get("name")
                    )
                    label = step.get("label") or step.get("title")
                    if code and label:
                        label_map[code] = label
    except Exception:
        label_map = {}
    return label_map


def transition_allowed(dept: str, from_status: str, to_status: str) -> bool:
    """Decide whether `dept` may move from `from_status` to `to_status`.

    If an active `Workflow` exists for the department (or a global one), its
    `spec` takes precedence. Otherwise fall back to hard-coded
    `ALLOWED_TRANSITIONS` for legacy behavior.
    """
    try:
        # Load any active workflow (dept-scoped first, then global)
        active_wf = _active_workflow_for_department(dept)

        # Also load any inactive workflow for this scope (dept-scoped then global)
        inactive_wf = _inactive_workflow_for_department(dept)

        legacy_allowed = ALLOWED_TRANSITIONS.get(dept, set())

        # Start with legacy map, then augment/override with active workflow spec if present
        allowed = set(legacy_allowed)
        if active_wf and active_wf.spec:
            spec = active_wf.spec or {}
            spec_allowed = _allowed_from_spec(spec)
            mode = (spec.get("mode") or "augment").strip().lower()
            if mode == "override":
                allowed = set(spec_allowed)
            else:
                allowed = allowed.union(spec_allowed)

            # Apply any explicit deny entries from the active spec
            deny_raw = spec.get("deny") or spec.get("deny_transitions") or []
            deny_set = set()
            if isinstance(deny_raw, dict):
                for k, vals in deny_raw.items():
                    if isinstance(vals, (list, tuple)):
                        for v in vals:
                            deny_set.add((k, v))
            elif isinstance(deny_raw, (list, tuple)):
                for item in deny_raw:
                    if isinstance(item, dict):
                        f = item.get("from") or item.get("source")
                        t = item.get("to") or item.get("target")
                        if f and t:
                            deny_set.add((f, t))
                    elif isinstance(item, (list, tuple)) and len(item) >= 2:
                        deny_set.add((item[0], item[1]))

            if deny_set:
                allowed = allowed.difference(deny_set)

        # If an inactive workflow exists for this scope with a spec, treat its
        # transitions as explicitly disabled (remove them from allowed set).
        if inactive_wf and inactive_wf.spec:
            disabled = _allowed_from_spec(inactive_wf.spec)
            if disabled:
                allowed = allowed.difference(disabled)

        return (from_status, to_status) in allowed
    except Exception:
        # On any DB/spec parse error, fall back to legacy map
        pass

    return (from_status, to_status) in ALLOWED_TRANSITIONS.get(dept, set())


def allowed_transitions_with_labels(dept: str, from_status: str) -> list:
    """Return a list of `(to_status, label)` choices allowed for `dept` from `from_status`.

    Labels are taken from an active workflow spec `steps` mapping when present,
    falling back to a `StatusOption` label in the DB or a humanized status string.
    """
    choices = []
    label_map = {}
    try:
        label_map = _status_label_map_from_workflow(
            _active_workflow_for_department(dept)
        )
    except Exception:
        pass

    allowed = set()
    try:
        wf = _active_workflow_for_department(dept)
        if wf and wf.spec:
            allowed = _allowed_from_spec(wf.spec)
    except Exception:
        # fall back to legacy map
        allowed = set()

    # If no workflow-defined allowed set, use legacy ALLOWED_TRANSITIONS
    if not allowed:
        allowed = ALLOWED_TRANSITIONS.get(dept, set())

    tos = sorted({t for (f, t) in allowed if f == from_status})
    for t in tos:
        lab = label_map.get(t)
        if not lab:
            try:
                from ..models import StatusOption

                so = StatusOption.query.filter_by(code=t).first()
                if so and so.label:
                    lab = so.label
            except Exception:
                lab = None
        if not lab:
            lab = t.replace("_", " ").title()
        choices.append((t, lab))
    return choices


def allowed_transition_routes(dept: str, from_status: str) -> list[dict]:
    """Return workflow-aware transition routes with optional target departments."""

    routes = []
    try:
        active_wf = _active_workflow_for_department(dept)
        inactive_wf = _inactive_workflow_for_department(dept)
        legacy_allowed = set(ALLOWED_TRANSITIONS.get(dept, set()))
        allowed = set(legacy_allowed)
        spec_entries = []

        if active_wf and active_wf.spec:
            spec = active_wf.spec or {}
            spec_entries = _transition_entries_from_spec(spec)
            spec_allowed = {(entry["from"], entry["to"]) for entry in spec_entries}
            mode = (spec.get("mode") or "augment").strip().lower()
            if mode == "override":
                allowed = set(spec_allowed)
            else:
                allowed = allowed.union(spec_allowed)

            deny_raw = spec.get("deny") or spec.get("deny_transitions") or []
            deny_set = set()
            if isinstance(deny_raw, dict):
                for source, targets in deny_raw.items():
                    if not isinstance(targets, (list, tuple)):
                        continue
                    for target in targets:
                        deny_set.add((source, target))
            elif isinstance(deny_raw, (list, tuple)):
                for item in deny_raw:
                    if isinstance(item, dict):
                        source = item.get("from") or item.get("source")
                        target = item.get("to") or item.get("target")
                        if source and target:
                            deny_set.add((source, target))
                    elif isinstance(item, (list, tuple)) and len(item) >= 2:
                        deny_set.add((item[0], item[1]))
            if deny_set:
                allowed = allowed.difference(deny_set)

        if inactive_wf and inactive_wf.spec:
            disabled = _allowed_from_spec(inactive_wf.spec)
            if disabled:
                allowed = allowed.difference(disabled)

        label_map = _status_label_map_from_workflow(active_wf)
        seen = set()
        for source, to_status in sorted(allowed):
            if source != from_status:
                continue
            matching_entries = [
                entry
                for entry in spec_entries
                if entry.get("from") == from_status and entry.get("to") == to_status
            ]
            if not matching_entries:
                matching_entries = [{"from": from_status, "to": to_status}]

            for entry in matching_entries:
                target_department = _normalize_route_department(
                    entry.get("to_dept")
                ) or owner_for_status(to_status)
                route_key = (to_status, target_department)
                if route_key in seen:
                    continue
                seen.add(route_key)
                label = label_map.get(to_status)
                if not label:
                    try:
                        so = StatusOption.query.filter_by(code=to_status).first()
                        if so and so.label:
                            label = so.label
                    except Exception:
                        label = None
                if not label:
                    label = to_status.replace("_", " ").title()
                routes.append(
                    {
                        "to_status": to_status,
                        "label": label,
                        "from_department": _normalize_route_department(
                            entry.get("from_dept")
                        )
                        or dept,
                        "to_department": target_department,
                    }
                )
    except Exception:
        routes = []

    if routes:
        return routes

    return [
        {
            "to_status": to_status,
            "label": label,
            "from_department": dept,
            "to_department": owner_for_status(to_status),
        }
        for to_status, label in allowed_transitions_with_labels(dept, from_status)
    ]


def handoff_for_transition(
    from_status: str, to_status: str
) -> Optional[Tuple[str, str]]:
    if (from_status, to_status) not in HANDOFF_TRANSITIONS:
        return None
    if (from_status, to_status) == ("B_IN_PROGRESS", "PENDING_C_REVIEW"):
        return ("B", "C")
    if (from_status, to_status) == ("NEW_FROM_A", "PENDING_C_REVIEW"):
        return ("B", "C")
    if from_status == "PENDING_C_REVIEW" and to_status in (
        "C_APPROVED",
        "C_NEEDS_CHANGES",
    ):
        return ("C", "B")
    if (from_status, to_status) == ("B_FINAL_REVIEW", "SENT_TO_A"):
        return ("B", "A")
    if (from_status, to_status) == ("EXEC_APPROVAL", "SENT_TO_A"):
        return ("B", "A")
    return None
