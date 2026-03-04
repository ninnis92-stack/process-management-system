from typing import Optional, Tuple

OWNER_BY_STATUS = {
    "PENDING_C_REVIEW": "C",
    "SENT_TO_A": "A",
}
DEFAULT_OWNER = "B"

def owner_for_status(status: str) -> str:
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