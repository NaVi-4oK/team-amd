from datetime import datetime, timezone
from uuid import uuid4
from core.contracts import Tool, ToolResult
from core.datasets import Dataset, DatasetRepository
from core.errors import DomainError
from core.job import JobKind


class ProcessingTool(Tool):

    job_kind = JobKind.PROCESS

    def __init__(self, datasets: DatasetRepository):
        self._datasets = datasets

        self._methods = {
            "count_records": self._count_records,
        }

    def _invalid(self, field, message):
        raise DomainError(
            "invalid_processing_request",
            message,
            {"field": field},
        )

    def _get_raw_dataset(self, dataset_id):

        try:
            dataset = self._datasets.get(dataset_id)

        except DomainError as error:
            if error.code == "dataset_not_found":
                raise DomainError(
                    "raw_dataset_not_found",
                    "Raw dataset not found",
                    {"field": "raw_dataset_id"},
                ) from None

            raise

        if dataset.dataset_kind != "raw":
            raise DomainError(
                "raw_dataset_not_found",
                "Requested dataset is not raw",
                {"field": "raw_dataset_id"},
            )

        return dataset

    def validate(self, parameters):

        required = {
            "raw_dataset_id",
            "method_id",
            "parameters",
        }

        for field in sorted(required):
            if field not in parameters:
                self._invalid(
                    field,
                    "Required field is missing",
                )

        for field in parameters:
            if field not in required:
                self._invalid(
                    field,
                    "Unknown field",
                )

        for field in ("raw_dataset_id", "method_id"):
            value = parameters[field]

            if (
                not isinstance(value, str)
                or not value.strip()
            ):
                self._invalid(
                    field,
                    "Non-empty string is required",
                )

        method_parameters = parameters["parameters"]

        if not isinstance(method_parameters, dict):
            self._invalid(
                "parameters",
                "Method parameters must be an object",
            )

        method_id = parameters["method_id"]

        if method_id not in self._methods:
            raise DomainError(
                "method_not_supported",
                "Processing method is not supported",
                {"field": "method_id"},
            )

        if method_id == "count_records" and method_parameters:
            self._invalid(
                "parameters",
                "count_records does not accept parameters",
            )

        self._get_raw_dataset(
            parameters["raw_dataset_id"]
        )

    def _count_records(self, records, parameters):
        return [
            {"source_record_count": len(records)}
        ]

    def _extract_records(self, dataset):

        content = dataset.content

        if not isinstance(content, dict):
            raise DomainError(
                "processing_input_invalid",
                "Invalid raw dataset content",
            )

        records = content.get("records")

        if (
            not isinstance(records, list)
            or any(
                not isinstance(row, list)
                for row in records
            )
            or len(records) != dataset.record_count
        ):
            raise DomainError(
                "processing_input_invalid",
                "Invalid raw dataset records",
            )

        return records

    def execute(self, parameters, job_id=None):

        if job_id is None:
            raise DomainError(
                "internal_error",
                "Processing requires a Job",
            )

        raw = self._get_raw_dataset(
            parameters["raw_dataset_id"]
        )

        method_id = parameters["method_id"]
        method_parameters = parameters["parameters"]

        records = self._extract_records(raw)

        try:
            method = self._methods[method_id]

            result = method(
                records,
                method_parameters,
            )

            if not isinstance(result, list):
                raise ValueError("Invalid method result")

        except DomainError:
            raise

        except Exception:
            raise DomainError(
                "processing_failed",
                "Dataset processing failed",
            ) from None

        dataset_id = str(uuid4())

        completed_at = datetime.now(
            timezone.utc
        ).isoformat()

        provenance = {
            "source_raw_dataset_id": raw.dataset_id,
            "method_id": method_id,
            "parameters": method_parameters,
            "source_provenance": raw.provenance,
            "completed_at": completed_at,
        }

        dataset = Dataset(
            dataset_id=dataset_id,
            dataset_kind="processed",
            job_id=job_id,
            record_count=len(result),
            created_at=completed_at,
            provenance=provenance,
            content={"records": result},
            observatory_id=raw.observatory_id,
            source_raw_dataset_id=raw.dataset_id,
            time_range=raw.time_range,
        )

        self._datasets.save(dataset)

        return ToolResult(
            dataset_id=dataset_id,
            data={
                "job_id": job_id,
                "processed_dataset_id": dataset_id,
                "source_raw_dataset_id": raw.dataset_id,
                "method_id": method_id,
                "parameters": method_parameters,
                "completed_at": completed_at,
                "record_count": len(result),
                "result_metadata": provenance,
            },
        )
