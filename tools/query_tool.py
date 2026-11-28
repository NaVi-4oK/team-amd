
from copy import deepcopy
from datetime import datetime
from threading import Lock
from uuid import uuid4

from core.contracts import Tool, ToolResult
from core.datasets import DatasetRepository
from core.errors import DomainError


class QueryTool(Tool):

    job_kind = None

    DEFAULT_LIMIT = 100
    MAX_LIMIT = 1000

    def __init__(self, datasets: DatasetRepository):
        self._datasets = datasets
        self._cursors = {}
        self._lock = Lock()

    def _invalid(self, field, message):
        raise DomainError(
            "invalid_query",
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
            self._invalid(field, "Invalid datetime")

    def _signature(self, parameters):
        signature = {
            key: value
            for key, value in parameters.items()
            if key != "cursor"
        }

        signature.setdefault(
            "limit", self.DEFAULT_LIMIT
        )

        return signature

    def validate(self, parameters):

        allowed = {
            "dataset_kind",
            "dataset_id",
            "observatory_id",
            "source_raw_dataset_id",
            "time_range",
            "limit",
            "cursor",
        }

        for field in parameters:
            if field not in allowed:
                self._invalid(field, "Unknown field")

        if parameters.get("dataset_kind") not in (
            "raw", "processed"
        ):
            self._invalid(
                "dataset_kind",
                "Expected raw or processed",
            )

        string_fields = (
            "dataset_id",
            "observatory_id",
            "source_raw_dataset_id",
            "cursor",
        )

        for field in string_fields:
            if field in parameters:
                value = parameters[field]

                if (
                    not isinstance(value, str)
                    or not value.strip()
                ):
                    self._invalid(
                        field,
                        "Non-empty string is required",
                    )

        if (
            parameters["dataset_kind"] == "raw"
            and "source_raw_dataset_id" in parameters
        ):
            self._invalid(
                "source_raw_dataset_id",
                "Filter is available for processed datasets",
            )

        limit = parameters.get(
            "limit", self.DEFAULT_LIMIT
        )

        if (
            type(limit) is not int
            or not 1 <= limit <= self.MAX_LIMIT
        ):
            self._invalid(
                "limit",
                "Limit must be between 1 and 1000",
            )

        if "time_range" in parameters:
            period = parameters["time_range"]

            if (
                not isinstance(period, dict)
                or set(period) != {"start", "stop"}
            ):
                self._invalid(
                    "time_range",
                    "Start and stop are required",
                )

            start = self._parse_datetime(
                period["start"], "time_range.start"
            )

            stop = self._parse_datetime(
                period["stop"], "time_range.stop"
            )

            if start >= stop:
                self._invalid(
                    "time_range.stop",
                    "Stop must be later than start",
                )

        if "dataset_id" in parameters:
            for field in ("limit", "cursor"):
                if field in parameters:
                    self._invalid(
                        field,
                        "Pagination requires a list query",
                    )

        if "cursor" in parameters:
            with self._lock:
                saved = self._cursors.get(
                    parameters["cursor"]
                )

            if saved is None:
                self._invalid(
                    "cursor",
                    "Unknown cursor",
                )

            signature, _, _ = saved

            if signature != self._signature(parameters):
                self._invalid(
                    "cursor",
                    "Query filters have changed",
                )

    def _matches(self, dataset, parameters):

        if dataset.dataset_kind != parameters["dataset_kind"]:
            return False

        for field in (
            "observatory_id",
            "source_raw_dataset_id",
        ):
            if (
                field in parameters
                and getattr(dataset, field) != parameters[field]
            ):
                return False

        if "time_range" in parameters:
            if dataset.time_range is None:
                return False

            query = parameters["time_range"]

            query_start = self._parse_datetime(
                query["start"], "time_range.start"
            )

            query_stop = self._parse_datetime(
                query["stop"], "time_range.stop"
            )

            dataset_start = self._parse_datetime(
                dataset.time_range["start"],
                "time_range.start",
            )

            dataset_stop = self._parse_datetime(
                dataset.time_range["stop"],
                "time_range.stop",
            )

            if (
                dataset_start >= query_stop
                or dataset_stop <= query_start
            ):
                return False

        return True

    def _summary(self, dataset):
        return {
            "dataset_id": dataset.dataset_id,
            "dataset_kind": dataset.dataset_kind,
            "observatory_id": dataset.observatory_id,
            "source_raw_dataset_id": (
                dataset.source_raw_dataset_id
            ),
            "time_range": dataset.time_range,
            "record_count": dataset.record_count,
            "created_at": dataset.created_at,
            "provenance": dataset.provenance,
        }

    def _get_snapshot(self, parameters):

        datasets = [
            dataset
            for dataset in self._datasets.all()
            if self._matches(dataset, parameters)
        ]

        # Secondary sorting: dataset_id ascending.
        datasets.sort(
            key=lambda dataset: dataset.dataset_id
        )

        # Primary sorting: created_at descending.
        datasets.sort(
            key=lambda dataset: self._parse_datetime(
                dataset.created_at, "created_at"
            ),
            reverse=True,
        )

        return tuple(
            self._summary(dataset)
            for dataset in datasets
        )

    def execute(self, parameters, job_id=None):

        self.validate(parameters)

        if "dataset_id" in parameters:
            dataset = self._datasets.get(
                parameters["dataset_id"]
            )

            if not self._matches(dataset, parameters):
                raise DomainError(
                    "dataset_not_found",
                    "Dataset not found",
                    {
                        "dataset_id": parameters["dataset_id"],
                    },
                )

            result = self._summary(dataset)
            result["content"] = dataset.content

            return ToolResult(
                data=deepcopy(result)
            )

        limit = parameters.get(
            "limit", self.DEFAULT_LIMIT
        )

        signature = self._signature(parameters)

        if "cursor" in parameters:
            with self._lock:
                _, snapshot, offset = self._cursors[
                    parameters["cursor"]
                ]
        else:
            snapshot = self._get_snapshot(parameters)
            offset = 0

        end = offset + limit
        items = snapshot[offset:end]

        next_cursor = None

        if end < len(snapshot):
            next_cursor = str(uuid4())

            with self._lock:
                self._cursors[next_cursor] = (
                    deepcopy(signature),
                    snapshot,
                    end,
                )

        return ToolResult(
            data={
                "items": deepcopy(list(items)),
                "next_cursor": next_cursor,
            }
        )
