import unittest

from core.datasets import Dataset, InMemoryDatasetRepository
from core.dispatcher import Dispatcher
from core.errors import DomainError
from core.job import JobKind, JobState
from core.registry import Registry
from core.repository import InMemoryJobRepository
from tools.import_tool import ImportTool
from tools.processing_tool import ProcessingTool
from tools.query_tool import QueryTool
from tests.test_import_tool import FakeIntermagnetSource


class TestQueryTool(unittest.TestCase):

    def setUp(self):
        self.jobs = InMemoryJobRepository()

        self.datasets = InMemoryDatasetRepository(
            self.jobs
        )

        self.registry = Registry()

        self.registry.register(
            "query",
            QueryTool(self.datasets),
        )

        self.dispatcher = Dispatcher(
            self.registry,
            self.jobs,
        )

    def create_raw(
        self,
        dataset_id,
        observatory="ARS",
        created_at="2026-11-28T12:00:00Z",
    ):
        job, _ = self.jobs.get_or_create(
            operation="import",
            idempotency_key=f"import-{dataset_id}",
            parameters={
                "observatory_id": observatory,
            },
            kind=JobKind.IMPORT,
        )

        job.start()

        dataset = Dataset(
            dataset_id=dataset_id,
            dataset_kind="raw",
            job_id=job.id,
            record_count=1,
            created_at=created_at,
            provenance={
                "publication_state": "adjusted",
                "cadence": "PT1M",
            },
            content={
                "records": [
                    ["2026-09-30T00:00:00Z", 100.0],
                ],
            },
            observatory_id=observatory,
            time_range={
                "start": "2026-09-30T00:00:00Z",
                "stop": "2026-10-01T00:00:00Z",
            },
        )

        self.datasets.save(dataset)
        job.complete(dataset_id)

        return dataset

    def query(self, **parameters):
        return self.dispatcher.dispatch(
            "query", parameters
        ).data

    def test_get_dataset_by_id(self):
        raw = self.create_raw("raw-001")

        result = self.query(
            dataset_kind="raw",
            dataset_id=raw.dataset_id,
        )

        self.assertEqual(
            result["dataset_id"], raw.dataset_id
        )

        self.assertEqual(
            result["content"], raw.content
        )

        self.assertEqual(len(self.jobs.all()), 1)

    def test_unknown_dataset(self):
        with self.assertRaises(DomainError) as error:
            self.query(
                dataset_kind="raw",
                dataset_id="unknown",
            )

        self.assertEqual(
            error.exception.code,
            "dataset_not_found",
        )

    def test_invalid_parameters(self):

        cases = [
            ({"dataset_kind": "unknown"}, "dataset_kind"),
            ({"limit": 0}, "limit"),
            ({"limit": 1001}, "limit"),
            ({"limit": True}, "limit"),
            ({"unexpected": 1}, "unexpected"),
            (
                {"time_range": {}},
                "time_range",
            ),
            (
                {"source_raw_dataset_id": "raw-001"},
                "source_raw_dataset_id",
            ),
        ]

        for extra, field in cases:
            with self.subTest(field=field, extra=extra):

                parameters = {
                    "dataset_kind": "raw",
                }

                parameters.update(extra)

                with self.assertRaises(DomainError) as error:
                    self.query(**parameters)

                self.assertEqual(
                    error.exception.code,
                    "invalid_query",
                )

                self.assertEqual(
                    error.exception.details["field"],
                    field,
                )

        self.assertEqual(self.jobs.all(), [])

    def test_empty_page(self):
        result = self.query(dataset_kind="raw")

        self.assertEqual(result["items"], [])
        self.assertIsNone(result["next_cursor"])
        self.assertEqual(self.jobs.all(), [])

    def test_observatory_filter(self):
        self.create_raw("raw-001", "ARS")
        self.create_raw("raw-002", "HAD")

        result = self.query(
            dataset_kind="raw",
            observatory_id="ARS",
        )

        self.assertEqual(
            [
                item["dataset_id"]
                for item in result["items"]
            ],
            ["raw-001"],
        )

    def test_time_range_filter(self):
        self.create_raw("raw-001")

        matching = self.query(
            dataset_kind="raw",
            time_range={
                "start": "2026-09-30T12:00:00Z",
                "stop": "2026-10-02T00:00:00Z",
            },
        )

        self.assertEqual(
            len(matching["items"]), 1
        )

        non_matching = self.query(
            dataset_kind="raw",
            time_range={
                "start": "2026-10-02T00:00:00Z",
                "stop": "2026-10-03T00:00:00Z",
            },
        )

        self.assertEqual(
            non_matching["items"], []
        )

    def test_stable_sorting(self):

        self.create_raw("raw-002")
        self.create_raw("raw-001")

        self.create_raw(
            "raw-003",
            created_at="2026-11-28T13:00:00Z",
        )

        result = self.query(dataset_kind="raw")

        self.assertEqual(
            [
                item["dataset_id"]
                for item in result["items"]
            ],
            ["raw-003", "raw-001", "raw-002"],
        )

        for item in result["items"]:
            self.assertNotIn("content", item)

    def test_pagination_snapshot(self):

        for number in range(1, 4):
            self.create_raw(
                f"raw-00{number}"
            )

        first = self.query(
            dataset_kind="raw",
            limit=2,
        )

        self.assertEqual(
            [
                item["dataset_id"]
                for item in first["items"]
            ],
            ["raw-001", "raw-002"],
        )

        self.assertIsNotNone(
            first["next_cursor"]
        )

        # A new dataset appears between pages.
        self.create_raw(
            "raw-004",
            created_at="2026-11-28T13:00:00Z",
        )

        second = self.query(
            dataset_kind="raw",
            limit=2,
            cursor=first["next_cursor"],
        )

        self.assertEqual(
            [
                item["dataset_id"]
                for item in second["items"]
            ],
            ["raw-003"],
        )

        self.assertIsNone(
            second["next_cursor"]
        )

    def test_invalid_cursor(self):

        with self.assertRaises(DomainError) as error:
            self.query(
                dataset_kind="raw",
                cursor="unknown",
            )

        self.assertEqual(
            error.exception.code, "invalid_query"
        )

        self.assertEqual(
            error.exception.details["field"], "cursor"
        )

    def test_cursor_rejects_changed_filters(self):

        self.create_raw("raw-001")
        self.create_raw("raw-002")

        first = self.query(
            dataset_kind="raw",
            limit=1,
        )

        with self.assertRaises(DomainError) as error:
            self.query(
                dataset_kind="raw",
                limit=1,
                observatory_id="HAD",
                cursor=first["next_cursor"],
            )

        self.assertEqual(
            error.exception.code, "invalid_query"
        )

    def test_full_import_process_query_workflow(self):

        source = FakeIntermagnetSource()

        self.registry.register(
            "import",
            ImportTool(source, self.datasets),
        )

        self.registry.register(
            "process",
            ProcessingTool(self.datasets),
        )

        import_job = self.dispatcher.dispatch(
            "import",
            {
                "observatory_id": "ARS",
                "publication_state": "adjusted",
                "cadence": "PT1M",
                "components": "xyzf",
                "start": "2026-09-30T00:00:00Z",
                "stop": "2026-10-01T00:00:00Z",
            },
            "import-001",
        )

        self.assertEqual(
            import_job.state, JobState.COMPLETED
        )

        process_job = self.dispatcher.dispatch(
            "process",
            {
                "raw_dataset_id": import_job.dataset_id,
                "method_id": "count_records",
                "parameters": {},
            },
            "process-001",
        )

        self.assertEqual(
            process_job.state, JobState.COMPLETED
        )

        result = self.query(
            dataset_kind="processed",
            dataset_id=process_job.dataset_id,
        )

        self.assertEqual(
            result["content"]["records"],
            [{"source_record_count": 2}],
        )

        self.assertEqual(
            result["source_raw_dataset_id"],
            import_job.dataset_id,
        )

        page = self.query(
            dataset_kind="processed",
            source_raw_dataset_id=import_job.dataset_id,
        )

        self.assertEqual(len(page["items"]), 1)

        self.assertEqual(source.calls, 1)
        self.assertEqual(len(self.jobs.all()), 2)
        self.assertEqual(len(self.datasets.all()), 2)


if __name__ == "__main__":
    unittest.main()
