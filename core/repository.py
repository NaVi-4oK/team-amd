
import json

from threading import Lock
from typing import Any, Dict, List, Protocol, Tuple
from core.errors import DomainError
from core.job import Job, JobKind


class JobRepository(Protocol):

    def get_or_create(
        self,
        operation: str,
        idempotency_key: str,
        parameters: Dict[str, Any],
        kind: JobKind,
    ) -> Tuple[Job, bool]:
        ...

    def get(self, job_id: str) -> Job:
        ...

    def all(self) -> List[Job]:
        ...


class InMemoryJobRepository:

    def __init__(self):
        self._jobs: Dict[str, Job] = {}
        self._keys: Dict[str, Tuple[str, str]] = {}
        self._lock = Lock()

    def get_or_create(
        self,
        operation: str,
        idempotency_key: str,
        parameters: Dict[str, Any],
        kind: JobKind,
    ) -> Tuple[Job, bool]:

        if (
            not isinstance(idempotency_key, str)
            or not idempotency_key.strip()
        ):
            raise DomainError(
                "invalid_parameters",
                "Idempotency key is required",
                {"field": "idempotency_key"},
            )

        signature = json.dumps(
            {
                "operation": operation,
                "parameters": parameters,
            },
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )

        with self._lock:
            existing = self._keys.get(idempotency_key)

            if existing is not None:
                previous_signature, job_id = existing

                if previous_signature != signature:
                    raise DomainError(
                        "idempotency_conflict",
                        "Idempotency key is already used "
                        "with different parameters",
                        {"field": "idempotency_key"},
                    )

                return self._jobs[job_id], False

            job = Job(kind)

            self._jobs[job.id] = job
            self._keys[idempotency_key] = (
                signature,
                job.id,
            )

            return job, True

    def get(self, job_id: str) -> Job:
        with self._lock:
            if job_id not in self._jobs:
                raise DomainError(
                    "job_not_found",
                    f"Job not found: {job_id}",
                    {"job_id": job_id},
                )

            return self._jobs[job_id]

    def all(self) -> List[Job]:
        with self._lock:
            return list(self._jobs.values())
