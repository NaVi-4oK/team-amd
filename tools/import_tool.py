import json
import re

from datetime import datetime, timezone
from uuid import uuid4
from core.contracts import Tool, ToolResult
from core.datasets import Dataset, DatasetRepository
from core.errors import DomainError
from core.intermagnet import IntermagnetSource, HapiResponse
from core.job import JobKind


class ImportTool(Tool):

    job_kind = JobKind.IMPORT

    PUBLICATION_STATES = {
        "adjusted",
        "definitive",
        "quasi-def",
        "reported",
        "best-avail",
    }

    CADENCES = {"PT1M", "PT1S"}

    COMPONENTS = {
        "xyzf",
        "hdzf",
        "diff",
        "native",
    }

    def __init__(
        self,
        source: IntermagnetSource,
        datasets: DatasetRepository,
    ):
        self._source = source
        self._datasets = datasets

    def _invalid(self, field, message):
        raise DomainError(
            "invalid_import_request",
            message,
            {"field": field},
        )

    def _parse_datetime(self, value, field):
        if not isinstance(value, str):
            self._invalid(field, "Expected datetime string")

        try:
            result = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )

            if result.tzinfo is None:
                raise ValueError()

            return result

        except ValueError:
            self._invalid(
                field,
                "Invalid datetime or missing timezone",
            )

    def validate(self, parameters):

        required = {
            "observatory_id",
            "publication_state",
            "cadence",
            "components",
            "start",
            "stop",
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

        observatory_id = parameters["observatory_id"]

        if (
            not isinstance(observatory_id, str)
            or not re.fullmatch(
                r"[A-Z]{3}", observatory_id
            )
        ):
            self._invalid(
                "observatory_id",
                "Expected a three-letter IAGA code",
            )

        choices = {
            "publication_state": self.PUBLICATION_STATES,
            "cadence": self.CADENCES,
            "components": self.COMPONENTS,
        }

        for field, allowed in choices.items():
            value = parameters[field]

            if (
                not isinstance(value, str)
                or value not in allowed
            ):
                self._invalid(
                    field,
                    "Unsupported value",
                )

        start = self._parse_datetime(
            parameters["start"], "start"
        )

        stop = self._parse_datetime(
            parameters["stop"], "stop"
        )

        if start >= stop:
            self._invalid(
                "stop",
                "Stop must be later than start",
            )

    def _check_status(self, status):

        if status in {1200, 1201}:
            return

        if status in {1406, 1407}:
            raise DomainError(
                "dataset_unavailable",
                "Requested INTERMAGNET dataset is unavailable",
                {"hapi_status": status},
            )

        if 1400 <= status < 1500:
            raise DomainError(
                "intermagnet_request_rejected",
                "INTERMAGNET rejected the request",
                {"hapi_status": status},
            )

        if 1500 <= status < 1600:
            raise DomainError(
                "intermagnet_unavailable",
                "INTERMAGNET is unavailable",
                {"hapi_status": status},
            )

        raise DomainError(
            "intermagnet_invalid_response",
            "Unknown HAPI status",
        )

    def _fetch(self, parameters):

        # Не более двух попыток получения данных.
        for attempt in range(2):
            try:
                response = self._source.fetch(parameters)

                if (
                    not isinstance(response, HapiResponse)
                    or type(response.status) is not int
                ):
                    raise DomainError(
                        "intermagnet_invalid_response",
                        "Invalid source response",
                    )

                self._check_status(response.status)

                return response

            except (TimeoutError, OSError):
                if attempt == 1:
                    raise DomainError(
                        "intermagnet_unavailable",
                        "INTERMAGNET connection failed",
                    ) from None

            except DomainError as error:
                if (
                    error.code != "intermagnet_unavailable"
                    or attempt == 1
                ):
                    raise

    def _read_records(self, response):

        try:
            if not isinstance(response.body, str):
                raise ValueError()

            payload = json.loads(response.body)

            if not isinstance(payload, dict):
                raise ValueError()

            if payload["status"]["code"] != response.status:
                raise ValueError()

            if response.status == 1201:
                records = payload.get("data", [])

                if records != []:
                    raise ValueError()
            else:
                records = payload["data"]

            if not isinstance(records, list):
                raise ValueError()

            if any(
                not isinstance(row, list)
                for row in records
            ):
                raise ValueError()

            return records

        except (ValueError, TypeError, KeyError):
            raise DomainError(
                "intermagnet_invalid_response",
                "Invalid HAPI response body",
            ) from None

    def execute(self, parameters, job_id=None):

        if job_id is None:
            raise DomainError(
                "internal_error",
                "Import requires a Job",
            )

        response = self._fetch(parameters)

        if (
            not isinstance(response.dataset_id, str)
            or not response.dataset_id
            or not isinstance(response.metadata, dict)
        ):
            raise DomainError(
                "intermagnet_invalid_response",
                "Invalid dataset metadata",
            )

        records = self._read_records(response)

        dataset_id = str(uuid4())

        retrieved_at = datetime.now(
            timezone.utc
        ).isoformat()

        provenance = {
            "intermagnet_dataset_id": response.dataset_id,
            "publication_state": parameters["publication_state"],
            "cadence": parameters["cadence"],
            "components": parameters["components"],
            "hapi_status": response.status,
            "source_metadata": response.metadata,
            "retrieved_at": retrieved_at,
            "format": "json",
        }

        dataset = Dataset(
            dataset_id=dataset_id,
            dataset_kind="raw",
            job_id=job_id,
            record_count=len(records),
            created_at=retrieved_at,
            provenance=provenance,
            content={
                "raw_body": response.body,
                "records": records,
            },
            observatory_id=parameters["observatory_id"],
            time_range={
                "start": parameters["start"],
                "stop": parameters["stop"],
            },
        )

        self._datasets.save(dataset)

        return ToolResult(
            dataset_id=dataset_id,
            data={
                "job_id": job_id,
                "raw_dataset_id": dataset_id,
                "intermagnet_dataset_id": response.dataset_id,
                "record_count": len(records),
                "retrieved_at": retrieved_at,
                "source_metadata": provenance,
            },
        )
