"""Domain models — aligned with official workshop schema."""
from dataclasses import dataclass, asdict, field


@dataclass
class BookingRequest:
    saga_id: str             # UUID string
    conversation_id: str     # UUID string
    user_id: str             # passenger name / user identifier
    origin: str
    destination: str
    date: str                # YYYY-MM-DD

    def to_dict(self) -> dict:
        return asdict(self)


class StepStatus:
    PENDING      = "pending"
    COMPLETED    = "completed"
    FAILED       = "failed"


class SagaStatus:
    IN_PROGRESS = "in_progress"
    COMPLETED   = "completed"
    FAILED      = "failed"


class SeatConflict(Exception):
    """Raised when OCC finds no available seat or a concurrent agent won the race."""


class BookingError(Exception):
    """Raised for unrecoverable booking failures."""


# Ordered saga steps and their compensating counterparts
SAGA_STEPS: list[tuple[str, str]] = [
    ("hold_seat",          "release_seat"),
    ("authorize_payment",  "void_authorization"),
    ("confirm_booking",    "cancel_booking"),
]

STEP_NAMES       = [s for s, _ in SAGA_STEPS]
COMPENSATION_MAP = {step: comp for step, comp in SAGA_STEPS}
