import json

from threading import Lock
from typing import Any, Dict, List, Optional, Protocol, Tuple
from core.errors import DomainError
from core.job import Job, JobKind

class JobRepository(Protocol):

    def find_existing(
        self,
        operation: str,
        idempotency_key: str,
        parameters: Dict[str, Any],
    ) -> Optional[Job]:
        ...

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

    def _request_signature(
        self,
        operation,
        idempotency_key,
        parameters,
    ):
        if (
            not isinstance(idempotency_key, str)
            or not idempotency_key.strip()
        ):
            raise DomainError(
                "invalid_parameters",
                "Idempotency key is required",
                {"field": "idempotency_key"},
            )

        try:
            return json.dumps(
                {
                    "operation": operation,
                    "parameters": parameters,
                },
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            )

        except (TypeError, ValueError):
            raise DomainError(
                "invalid_parameters",
                "Parameters must be JSON-compatible",
                {"field": "parameters"},
            ) from None

    def find_existing(
        self,
        operation,
        idempotency_key,
        parameters,
    ):
        signature = self._request_signature(
            operation,
            idempotency_key,
            parameters,
        )

        with self._lock:
            existing = self._keys.get(idempotency_key)

            if existing is None:
                return None

            previous_signature, job_id = existing

            if previous_signature != signature:
                raise DomainError(
                    "idempotency_conflict",
                    "Idempotency key is already used "
                    "with different parameters",
                    {"field": "idempotency_key"},
                )

            return self._jobs[job_id]

    def get_or_create(
        self,
        operation: str,
        idempotency_key: str,
        parameters: Dict[str, Any],
        kind: JobKind,
    ) -> Tuple[Job, bool]:

        signature = self._request_signature(
            operation,
            idempotency_key,
            parameters,
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
