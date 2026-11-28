import unittest

from unittest.mock import patch
from core.datasets import Dataset, InMemoryDatasetRepository
from core.dispatcher import Dispatcher
from core.errors import DomainError
from core.job import JobKind, JobState
from core.registry import Registry
from core.repository import InMemoryJobRepository
from tools.processing_tool import ProcessingTool


class TestProcessingTool(unittest.TestCase):

    def setUp(self):
        self.jobs = InMemoryJobRepository()

        self.datasets = InMemoryDatasetRepository(
            self.jobs
        )

        self.registry = Registry()

        self.tool = ProcessingTool(self.datasets)

        self.registry.register(
            "process",
            self.tool,
        )

        self.dispatcher = Dispatcher(
            self.registry,
            self.jobs,
        )

        self.parameters = {
            "raw_dataset_id": "raw-001",
            "method_id": "count_records",
            "parameters": {},
        }

    def create_raw(self, records=None, malformed=False):

        if records is None:
            records = [
                ["2026-09-30T00:00:00Z", 100.0],
                ["2026-09-30T00:01:00Z", 110.0],
            ]

        job, _ = self.jobs.get_or_create(
            operation="import",
            idempotency_key="import-001",
            parameters={"observatory_id": "ARS"},
            kind=JobKind.IMPORT,
        )

        job.start()

        content = {"records": records}

        if malformed:
            content = {"invalid": records}

        raw = Dataset(
            dataset_id="raw-001",
            dataset_kind="raw",
            job_id=job.id,
            record_count=len(records),
            created_at="2026-11-28T12:00:00Z",
            provenance={
                "cadence": "PT1M",
                "publication_state": "adjusted",
            },
            content=content,
            observatory_id="ARS",
            time_range={
                "start": "2026-09-30T00:00:00Z",
                "stop": "2026-10-01T00:00:00Z",
            },
        )

        self.datasets.save(raw)
        job.complete(raw.dataset_id)

        return raw

    def run_processing(self, key="process-001"):
        return self.dispatcher.dispatch(
            "process",
            self.parameters,
            key,
        )

    def test_successful_processing(self):
        raw = self.create_raw()

        job = self.run_processing()

        self.assertEqual(
            job.state, JobState.COMPLETED
        )

        result = self.datasets.get(job.dataset_id)

        self.assertEqual(
            result.dataset_kind,
            "processed",
        )

        self.assertNotEqual(
            result.dataset_id,
            raw.dataset_id,
        )

        self.assertEqual(
            result.source_raw_dataset_id,
            raw.dataset_id,
        )

        self.assertEqual(
            result.content["records"],
            [{"source_record_count": 2}],
        )

        self.assertEqual(result.record_count, 1)

        self.assertEqual(
            self.datasets.get(raw.dataset_id),
            raw,
        )

    def test_invalid_parameters(self):
        self.create_raw()

        self.parameters["parameters"] = {
            "unexpected": True,
        }

        with self.assertRaises(DomainError) as error:
            self.run_processing()

        self.assertEqual(
            error.exception.code,
            "invalid_processing_request",
        )

        self.assertEqual(
            error.exception.details["field"],
            "parameters",
        )

        self.assertEqual(len(self.jobs.all()), 1)

    def test_unknown_method(self):
        self.create_raw()

        self.parameters["method_id"] = "unknown"

        with self.assertRaises(DomainError) as error:
            self.run_processing()

        self.assertEqual(
            error.exception.code,
            "method_not_supported",
        )

        self.assertEqual(len(self.jobs.all()), 1)

    def test_missing_raw_dataset(self):

        with self.assertRaises(DomainError) as error:
            self.run_processing()

        self.assertEqual(
            error.exception.code,
            "raw_dataset_not_found",
        )

        self.assertEqual(self.jobs.all(), [])

    def test_processed_dataset_is_not_raw(self):
        self.create_raw()

        first = self.run_processing()

        self.parameters["raw_dataset_id"] = (
            first.dataset_id
        )

        with self.assertRaises(DomainError) as error:
            self.run_processing("process-002")

        self.assertEqual(
            error.exception.code,
            "raw_dataset_not_found",
        )

        self.assertEqual(len(self.jobs.all()), 2)

    def test_invalid_raw_content(self):
        self.create_raw(malformed=True)

        job = self.run_processing()

        self.assertEqual(job.state, JobState.FAILED)

        self.assertEqual(
            job.error.code,
            "processing_input_invalid",
        )

        self.assertEqual(len(self.datasets.all()), 1)

    def test_empty_raw_dataset(self):
        self.create_raw(records=[])

        job = self.run_processing()

        self.assertEqual(
            job.state, JobState.COMPLETED
        )

        result = self.datasets.get(job.dataset_id)

        self.assertEqual(
            result.content["records"],
            [{"source_record_count": 0}],
        )

    def test_idempotent_processing(self):
        self.create_raw()

        first = self.run_processing()
        second = self.run_processing()

        self.assertIs(first, second)

        self.assertEqual(len(self.jobs.all()), 2)
        self.assertEqual(len(self.datasets.all()), 2)

    def test_new_key_creates_new_result(self):
        self.create_raw()

        first = self.run_processing("process-001")
        second = self.run_processing("process-002")

        self.assertNotEqual(first.id, second.id)

        self.assertNotEqual(
            first.dataset_id,
            second.dataset_id,
        )

        self.assertEqual(len(self.datasets.all()), 3)

    def test_processing_failure(self):
        self.create_raw()

        with patch.dict(
            self.tool._methods,
            {
                "count_records": self.failing_method,
            },
        ):
            job = self.run_processing()

        self.assertEqual(job.state, JobState.FAILED)

        self.assertEqual(
            job.error.code,
            "processing_failed",
        )

        self.assertEqual(len(self.datasets.all()), 1)

    def failing_method(self, records, parameters):
        raise RuntimeError("Processing failed")


if __name__ == "__main__":
    unittest.main()
