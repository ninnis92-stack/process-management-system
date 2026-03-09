from typing import List, Optional, Tuple

from ..models import ProcessFlowStep, ProcessStatus

OWNER_BY_STATUS = {
    "PENDING_C_REVIEW": "C",
    "SENT_TO_A": "A",
}
DEFAULT_OWNER = "B"

def owner_for_status(status: str, current_owner: Optional[str] = None) -> str:
    configured = ProcessStatus.by_code(status)
    if configured and configured.is_active:
        if configured.behavior == "transfer" and configured.transfer_to_department:
            return configured.transfer_to_department
        if configured.behavior == "status_only":
            return current_owner or DEFAULT_OWNER

    if status == "CLOSED":
        return "B"
    return OWNER_BY_STATUS.get(status, DEFAULT_OWNER)

ALLOWED_TRANSITIONS = {
    "A": {
        ("SENT_TO_A", "B_IN_PROGRESS"),  # Reopen to Dept B
        ("SENT_TO_A", "CLOSED"),         # Approve/close
        ("CLOSED", "B_IN_PROGRESS"),     # Reopen after close
    },
    "B": {
        ("NEW_FROM_A", "B_IN_PROGRESS"),
        ("NEW_FROM_A", "PENDING_C_REVIEW"),
        ("NEW_FROM_A", "B_FINAL_REVIEW"),
        ("NEW_FROM_A", "CLOSED"),
        ("B_IN_PROGRESS", "PENDING_C_REVIEW"),
        ("B_IN_PROGRESS", "WAITING_ON_A_RESPONSE"),
        ("B_IN_PROGRESS", "B_FINAL_REVIEW"),  # bypass C (only if requires_c_review == False)
        ("WAITING_ON_A_RESPONSE", "B_IN_PROGRESS"),
        ("C_NEEDS_CHANGES", "B_IN_PROGRESS"),
        ("C_APPROVED", "B_FINAL_REVIEW"),
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
    ("B_IN_PROGRESS", "PENDING_C_REVIEW"),   # B -> C
    ("PENDING_C_REVIEW", "C_APPROVED"),      # C -> B
    ("PENDING_C_REVIEW", "C_NEEDS_CHANGES"), # C -> B
    ("B_FINAL_REVIEW", "SENT_TO_A"),         # B -> A/submitter
    ("EXEC_APPROVAL", "SENT_TO_A"),          # B -> A/submitter after exec signoff
    ("NEW_FROM_A", "PENDING_C_REVIEW"),      # B -> C (early send)
}

def transition_allowed(dept: str, from_status: str, to_status: str) -> bool:
    return (from_status, to_status) in ALLOWED_TRANSITIONS.get(dept, set())


def transition_allowed_for_request(req, dept: str, from_status: str, to_status: str) -> bool:
    """Use flow-group rules when configured, else fall back to static transitions."""
    if getattr(req, "flow_group_id", None):
        step = ProcessFlowStep.query.filter_by(
            flow_group_id=req.flow_group_id,
            actor_department=dept,
            from_status=from_status,
            to_status=to_status,
        ).first()
        if step:
            return True
    return transition_allowed(dept, from_status, to_status)


def transition_step_for_request(req, dept: str, from_status: str, to_status: str):
    """Return the configured step for this transition when a flow group is attached."""
    if not getattr(req, "flow_group_id", None):
        return None
    return ProcessFlowStep.query.filter_by(
        flow_group_id=req.flow_group_id,
        actor_department=dept,
        from_status=from_status,
        to_status=to_status,
    ).first()


def transition_options_for_request(req, dept: str, from_status: str) -> List[str]:
    """Return allowed destination statuses for this request/department/status."""
    if getattr(req, "flow_group_id", None):
        rows = (
            ProcessFlowStep.query
            .filter_by(
                flow_group_id=req.flow_group_id,
                actor_department=dept,
                from_status=from_status,
            )
            .order_by(ProcessFlowStep.sort_order.asc(), ProcessFlowStep.id.asc())
            .all()
        )
        # Keep stable order while removing duplicates.
        seen = set()
        values = []
        for row in rows:
            if row.to_status not in seen:
                seen.add(row.to_status)
                values.append(row.to_status)
        return values

    return [to for frm, to in ALLOWED_TRANSITIONS.get(dept, set()) if frm == from_status]


def requires_submission_for_request(req, dept: str, from_status: str, to_status: str) -> bool:
    """Return whether this transition requires a submission payload."""
    step = transition_step_for_request(req, dept, from_status, to_status)
    if step is not None:
        return bool(step.requires_submission)
    return False

def handoff_for_transition(from_status: str, to_status: str) -> Optional[Tuple[str, str]]:
    if (from_status, to_status) not in HANDOFF_TRANSITIONS:
        return None
    if (from_status, to_status) == ("B_IN_PROGRESS", "PENDING_C_REVIEW"):
        return ("B", "C")
    if (from_status, to_status) == ("NEW_FROM_A", "PENDING_C_REVIEW"):
        return ("B", "C")
    if from_status == "PENDING_C_REVIEW" and to_status in ("C_APPROVED", "C_NEEDS_CHANGES"):
        return ("C", "B")
    if (from_status, to_status) == ("B_FINAL_REVIEW", "SENT_TO_A"):
        return ("B", "A")
    if (from_status, to_status) == ("EXEC_APPROVAL", "SENT_TO_A"):
        return ("B", "A")
    return None


def handoff_for_request(req, dept: str, from_status: str, to_status: str) -> Optional[Tuple[str, str]]:
    """Resolve handoff from configured flow group first, then static mapping."""
    step = transition_step_for_request(req, dept, from_status, to_status)
    if step and step.from_department and step.to_department:
        return (step.from_department, step.to_department)
    return handoff_for_transition(from_status, to_status)


def owner_for_request_transition(req, dept: str, from_status: str, to_status: str) -> str:
    """Resolve target owner from configured flow step, else status-based owner."""
    step = transition_step_for_request(req, dept, from_status, to_status)
    if step and step.to_department:
        return step.to_department
    return owner_for_status(to_status, current_owner=getattr(req, "owner_department", None))