import json
import unittest

from core.datasets import InMemoryDatasetRepository
from core.dispatcher import Dispatcher
from core.errors import DomainError
from core.intermagnet import HapiResponse
from core.job import JobState
from core.registry import Registry
from core.repository import InMemoryJobRepository
from tools.import_tool import ImportTool


class FakeIntermagnetSource:

    def __init__(
        self,
        status=1200,
        malformed=False,
        unavailable=False,
    ):
        self.status = status
        self.malformed = malformed
        self.unavailable = unavailable
        self.calls = 0

    def fetch(self, parameters):
        self.calls += 1

        if self.unavailable:
            raise TimeoutError()

        records = []

        if self.status == 1200:
            records = [
                ["2026-09-30T00:00:00Z", 100.0],
                ["2026-09-30T00:01:00Z", 110.0],
            ]

        body = json.dumps({
            "status": {
                "code": self.status,
            },
            "data": records,
        })

        if self.malformed:
            body = "{invalid json"

        return HapiResponse(
            dataset_id="ARS/adjusted/PT1M/xyzf",
            status=self.status,
            metadata={
                "parameters": [
                    {"name": "Time"},
                    {"name": "X"},
                ],
            },
            body=body,
        )


class TestImportTool(unittest.TestCase):

    def setUp(self):
        self.jobs = InMemoryJobRepository()

        self.datasets = InMemoryDatasetRepository(
            self.jobs
        )

        self.registry = Registry()

        self.dispatcher = Dispatcher(
            self.registry,
            self.jobs,
        )

        self.parameters = {
            "observatory_id": "ARS",
            "publication_state": "adjusted",
            "cadence": "PT1M",
            "components": "xyzf",
            "start": "2026-09-30T00:00:00Z",
            "stop": "2026-10-01T00:00:00Z",
        }

    def register_source(self, source):
        self.registry.register(
            "import",
            ImportTool(source, self.datasets),
        )

    def run_import(self, key="import-001"):
        return self.dispatcher.dispatch(
            "import",
            self.parameters,
            key,
        )

    def test_successful_import(self):
        source = FakeIntermagnetSource()
        self.register_source(source)

        job = self.run_import()

        self.assertEqual(
            job.state, JobState.COMPLETED
        )

        dataset = self.datasets.get(job.dataset_id)

        self.assertEqual(dataset.dataset_kind, "raw")
        self.assertEqual(dataset.observatory_id, "ARS")
        self.assertEqual(dataset.record_count, 2)
        self.assertEqual(source.calls, 1)

        self.assertEqual(
            dataset.provenance["hapi_status"],
            1200,
        )

    def test_empty_successful_import(self):
        self.register_source(
            FakeIntermagnetSource(status=1201)
        )

        job = self.run_import()

        self.assertEqual(
            job.state, JobState.COMPLETED
        )

        dataset = self.datasets.get(job.dataset_id)

        self.assertEqual(dataset.record_count, 0)
        self.assertEqual(
            dataset.content["records"], []
        )

    def test_invalid_observatory(self):
        source = FakeIntermagnetSource()
        self.register_source(source)

        self.parameters["observatory_id"] = "INVALID"

        with self.assertRaises(DomainError) as error:
            self.run_import()

        self.assertEqual(
            error.exception.code,
            "invalid_import_request",
        )

        self.assertEqual(
            error.exception.details["field"],
            "observatory_id",
        )

        self.assertEqual(source.calls, 0)
        self.assertEqual(self.jobs.all(), [])

    def test_invalid_time_range(self):
        self.register_source(
            FakeIntermagnetSource()
        )

        self.parameters["stop"] = (
            self.parameters["start"]
        )

        with self.assertRaises(DomainError) as error:
            self.run_import()

        self.assertEqual(
            error.exception.code,
            "invalid_import_request",
        )

        self.assertEqual(
            error.exception.details["field"],
            "stop",
        )

        self.assertEqual(self.jobs.all(), [])

    def test_dataset_unavailable(self):
        self.register_source(
            FakeIntermagnetSource(status=1406)
        )

        job = self.run_import()

        self.assertEqual(job.state, JobState.FAILED)
        self.assertEqual(
            job.error.code,
            "dataset_unavailable",
        )
        self.assertEqual(self.datasets.all(), [])

    def test_request_rejected(self):
        self.register_source(
            FakeIntermagnetSource(status=1400)
        )

        job = self.run_import()

        self.assertEqual(job.state, JobState.FAILED)

        self.assertEqual(
            job.error.code,
            "intermagnet_request_rejected",
        )

        self.assertEqual(self.datasets.all(), [])

    def test_source_unavailable_with_retry(self):
        source = FakeIntermagnetSource(
            unavailable=True
        )

        self.register_source(source)

        job = self.run_import()

        self.assertEqual(job.state, JobState.FAILED)

        self.assertEqual(
            job.error.code,
            "intermagnet_unavailable",
        )

        self.assertEqual(source.calls, 2)
        self.assertEqual(self.datasets.all(), [])

    def test_malformed_response(self):
        self.register_source(
            FakeIntermagnetSource(malformed=True)
        )

        job = self.run_import()

        self.assertEqual(job.state, JobState.FAILED)

        self.assertEqual(
            job.error.code,
            "intermagnet_invalid_response",
        )

        self.assertEqual(self.datasets.all(), [])

    def test_idempotent_import(self):
        source = FakeIntermagnetSource()
        self.register_source(source)

        first = self.run_import()
        second = self.run_import()

        self.assertIs(first, second)
        self.assertEqual(source.calls, 1)
        self.assertEqual(len(self.datasets.all()), 1)


if __name__ == "__main__":
    unittest.main()
