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
        ("SENT_TO_A", "CLOSED"),         # Approve/close
        ("CLOSED", "B_IN_PROGRESS"),     # Reopen after close
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
        ("B_IN_PROGRESS", "B_FINAL_REVIEW"),  # bypass C (only if requires_c_review == False)
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
    ("B_IN_PROGRESS", "PENDING_C_REVIEW"),   # B -> C
    ("PENDING_C_REVIEW", "C_APPROVED"),      # C -> B
    ("PENDING_C_REVIEW", "C_NEEDS_CHANGES"), # C -> B
    ("B_FINAL_REVIEW", "SENT_TO_A"),         # B -> A/submitter
    ("EXEC_APPROVAL", "SENT_TO_A"),          # B -> A/submitter after exec signoff
    ("NEW_FROM_A", "PENDING_C_REVIEW"),      # B -> C (early send)
}

def _allowed_from_spec(spec: dict) -> set:
    """Return a set of (from,to) tuples from a workflow spec dict.

    Expected spec format (flexible):
      {"transitions": [{"from": "A", "to": "B"}, ...]}
    """
    out = set()
    if not spec or not isinstance(spec, dict):
        return out
    trans = spec.get('transitions') or spec.get('allowed_transitions') or []
    if isinstance(trans, dict):
        # support mapping format {"A": ["B","C"]}
        for k, vals in trans.items():
            if isinstance(vals, (list, tuple)):
                for v in vals:
                    out.add((k, v))
    elif isinstance(trans, (list, tuple)):
        for item in trans:
            if isinstance(item, dict):
                f = item.get('from') or item.get('source')
                t = item.get('to') or item.get('target')
                if f and t:
                    out.add((f, t))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                out.add((item[0], item[1]))
    return out


def transition_allowed(dept: str, from_status: str, to_status: str) -> bool:
    """Decide whether `dept` may move from `from_status` to `to_status`.

    If an active `Workflow` exists for the department (or a global one), its
    `spec` takes precedence. Otherwise fall back to hard-coded
    `ALLOWED_TRANSITIONS` for legacy behavior.
    """
    try:
        # Prefer department-scoped workflow, then global
        wf = Workflow.query.filter_by(active=True, department_code=dept).first()
        if not wf:
            wf = Workflow.query.filter_by(active=True, department_code=None).first()
        if wf and wf.spec:
            allowed = _allowed_from_spec(wf.spec)
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
        wf = Workflow.query.filter_by(active=True, department_code=dept).first()
        if not wf:
            wf = Workflow.query.filter_by(active=True, department_code=None).first()
        if wf and isinstance(wf.spec, dict):
            steps = wf.spec.get('steps') or wf.spec.get('labels')
            if isinstance(steps, dict):
                label_map.update(steps)
            elif isinstance(steps, (list, tuple)):
                for s in steps:
                    if isinstance(s, dict):
                        code = s.get('code') or s.get('id') or s.get('name')
                        lab = s.get('label') or s.get('title')
                        if code and lab:
                            label_map[code] = lab
    except Exception:
        # ignore DB/spec parsing issues and fall back to legacy behavior
        pass

    allowed = set()
    try:
        wf = Workflow.query.filter_by(active=True, department_code=dept).first()
        if not wf:
            wf = Workflow.query.filter_by(active=True, department_code=None).first()
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