from copy import deepcopy
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, List, Optional, Protocol
from core.errors import DomainError
from core.job import JobState
from core.repository import JobRepository


@dataclass
class Dataset:
    dataset_id: str
    dataset_kind: str
    job_id: str
    record_count: int
    created_at: str
    provenance: Dict[str, Any]
    content: Any

    observatory_id: Optional[str] = None
    source_raw_dataset_id: Optional[str] = None
    time_range: Optional[Dict[str, str]] = None


class DatasetRepository(Protocol):

    def save(self, dataset: Dataset) -> None:
        ...

    def get(self, dataset_id: str) -> Dataset:
        ...

    def all(self) -> List[Dataset]:
        ...


class InMemoryDatasetRepository:

    def __init__(self, jobs: JobRepository):
        self._jobs = jobs
        self._datasets: Dict[str, Dataset] = {}
        self._lock = Lock()

    def save(self, dataset: Dataset) -> None:
        if dataset.dataset_kind not in {"raw", "processed"}:
            raise DomainError(
                "storage_error",
                "Unsupported dataset kind",
            )

        if (
            not isinstance(dataset.record_count, int)
            or isinstance(dataset.record_count, bool)
            or dataset.record_count < 0
        ):
            raise DomainError(
                "storage_error",
                "Invalid record count",
            )

        expected_state = (
            JobState.DOWNLOADING
            if dataset.dataset_kind == "raw"
            else JobState.PROCESSING
        )

        job = self._jobs.get(dataset.job_id)

        if job.state != expected_state:
            raise DomainError(
                "storage_error",
                "Dataset must belong to a running Job",
            )

        if dataset.dataset_kind == "processed":
            source = self.get(dataset.source_raw_dataset_id)

            if source.dataset_kind != "raw":
                raise DomainError(
                    "storage_error",
                    "Source dataset must be raw",
                )

        with self._lock:
            if dataset.dataset_id in self._datasets:
                raise DomainError(
                    "storage_error",
                    "Dataset ID already exists",
                )

            self._datasets[dataset.dataset_id] = deepcopy(
                dataset
            )

    def _is_visible(self, dataset: Dataset) -> bool:
        job = self._jobs.get(dataset.job_id)

        return (
            job.state == JobState.COMPLETED
            and job.dataset_id == dataset.dataset_id
        )

    def get(self, dataset_id: str) -> Dataset:
        with self._lock:
            dataset = self._datasets.get(dataset_id)

            if (
                dataset is None
                or not self._is_visible(dataset)
            ):
                raise DomainError(
                    "dataset_not_found",
                    "Dataset not found",
                    {"dataset_id": dataset_id},
                )

            return deepcopy(dataset)

    def all(self) -> List[Dataset]:
        with self._lock:
            datasets = [
                deepcopy(dataset)
                for dataset in self._datasets.values()
                if self._is_visible(dataset)
            ]

        return sorted(
            datasets,
            key=lambda dataset: (
                dataset.created_at,
                dataset.dataset_id,
            ),
        )
