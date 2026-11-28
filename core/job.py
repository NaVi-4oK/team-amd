from enum import Enum
from threading import Lock
from uuid import uuid4

from core.errors import DomainError


class JobKind(str, Enum):
    IMPORT = "import"
    PROCESS = "process"


class JobState(str, Enum):
    CREATED = "Created"
    DOWNLOADING = "Downloading"
    PROCESSING = "Processing"
    COMPLETED = "Completed"
    FAILED = "Failed"


class Job:
    def __init__(self, kind: JobKind):
        self._id = str(uuid4())
        self._kind = JobKind(kind)
        self._state = JobState.CREATED
        self._dataset_id = None
        self._error = None
        self._lock = Lock()

    @property
    def id(self):
        return self._id

    @property
    def kind(self):
        return self._kind

    @property
    def state(self):
        return self._state

    @property
    def dataset_id(self):
        return self._dataset_id

    @property
    def error(self):
        return self._error

    def _working_state(self):
        if self.kind == JobKind.IMPORT:
            return JobState.DOWNLOADING

        return JobState.PROCESSING

    def _require_state(self, allowed, target):
        if self._state not in allowed:
            raise DomainError(
                "invalid_job_transition",
                f"Transition {self._state.value} "
                f"-> {target.value} is not allowed",
                {
                    "from": self._state.value,
                    "to": target.value,
                },
            )

    def start(self):
        with self._lock:
            target = self._working_state()

            self._require_state(
                {JobState.CREATED}, target
            )

            self._state = target

    def complete(self, dataset_id: str):
        with self._lock:
            self._require_state(
                {self._working_state()},
                JobState.COMPLETED,
            )

            if not isinstance(dataset_id, str) or not dataset_id.strip():
                raise DomainError(
                    "invalid_parameters",
                    "Dataset ID is required",
                    {"field": "dataset_id"},
                )

            self._dataset_id = dataset_id
            self._state = JobState.COMPLETED

    def fail(self, error: DomainError):
        with self._lock:
            self._require_state(
                {JobState.CREATED, self._working_state()},
                JobState.FAILED,
            )

            self._error = error
            self._state = JobState.FAILED

    def interrupt(self):
        with self._lock:
            self._require_state(
                {self._working_state()},
                JobState.FAILED,
            )

            self._error = DomainError(
                "job_interrupted",
                "Job was interrupted by application restart",
            )

            self._state = JobState.FAILED
