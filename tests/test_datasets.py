
import unittest

from core.datasets import Dataset, InMemoryDatasetRepository
from core.errors import DomainError
from core.job import JobKind
from core.repository import InMemoryJobRepository


class TestDatasetRepository(unittest.TestCase):

    def setUp(self):
        self.jobs = InMemoryJobRepository()
        self.datasets = InMemoryDatasetRepository(
            self.jobs
        )

    def create_raw(self, count=2):
        job, _ = self.jobs.get_or_create(
            operation="import",
            idempotency_key="import-001",
            parameters={"observatory_id": "ARS"},
            kind=JobKind.IMPORT,
        )

        job.start()

        dataset = Dataset(
            dataset_id="raw-001",
            dataset_kind="raw",
            job_id=job.id,
            record_count=count,
            created_at="2026-11-28T12:00:00Z",
            provenance={
                "publication_state": "adjusted",
                "cadence": "PT1M",
            },
            content=[10.0, 20.0] if count else [],
            observatory_id="ARS",
        )

        return job, dataset

    def test_save_and_get_dataset(self):
        job, dataset = self.create_raw()

        self.datasets.save(dataset)
        job.complete(dataset.dataset_id)

        result = self.datasets.get("raw-001")

        self.assertEqual(result.content, [10.0, 20.0])
        self.assertEqual(result.record_count, 2)
        self.assertEqual(result.observatory_id, "ARS")

    def test_unfinished_dataset_is_hidden(self):
        job, dataset = self.create_raw()

        self.datasets.save(dataset)

        with self.assertRaises(DomainError) as error:
            self.datasets.get(dataset.dataset_id)

        self.assertEqual(
            error.exception.code,
            "dataset_not_found",
        )
        self.assertEqual(self.datasets.all(), [])

        job.complete(dataset.dataset_id)

        self.assertEqual(len(self.datasets.all()), 1)

    def test_failed_dataset_is_hidden(self):
        job, dataset = self.create_raw()

        self.datasets.save(dataset)

        job.fail(
            DomainError(
                "storage_error",
                "Unable to finish import",
            )
        )

        self.assertEqual(self.datasets.all(), [])

        with self.assertRaises(DomainError):
            self.datasets.get(dataset.dataset_id)

    def test_duplicate_dataset_id(self):
        job, dataset = self.create_raw()

        self.datasets.save(dataset)

        with self.assertRaises(DomainError) as error:
            self.datasets.save(dataset)

        self.assertEqual(
            error.exception.code,
            "storage_error",
        )

    def test_unknown_dataset(self):
        with self.assertRaises(DomainError) as error:
            self.datasets.get("unknown")

        self.assertEqual(
            error.exception.code,
            "dataset_not_found",
        )

    def test_dataset_is_protected_from_changes(self):
        job, dataset = self.create_raw()

        self.datasets.save(dataset)
        job.complete(dataset.dataset_id)

        dataset.content.append(30.0)

        result = self.datasets.get("raw-001")
        result.content.append(40.0)

        self.assertEqual(
            self.datasets.get("raw-001").content,
            [10.0, 20.0],
        )

    def test_empty_raw_dataset(self):
        job, dataset = self.create_raw(count=0)

        self.datasets.save(dataset)
        job.complete(dataset.dataset_id)

        result = self.datasets.get("raw-001")

        self.assertEqual(result.record_count, 0)
        self.assertEqual(result.content, [])

    def test_processed_dataset_preserves_source(self):
        import_job, raw = self.create_raw()

        self.datasets.save(raw)
        import_job.complete(raw.dataset_id)

        process_job, _ = self.jobs.get_or_create(
            operation="process",
            idempotency_key="process-001",
            parameters={
                "raw_dataset_id": raw.dataset_id,
            },
            kind=JobKind.PROCESS,
        )

        process_job.start()

        processed = Dataset(
            dataset_id="processed-001",
            dataset_kind="processed",
            job_id=process_job.id,
            record_count=1,
            created_at="2026-11-28T12:01:00Z",
            provenance={"method_id": "test_method"},
            content=[15.0],
            source_raw_dataset_id=raw.dataset_id,
        )

        self.datasets.save(processed)
        process_job.complete(processed.dataset_id)

        self.assertEqual(len(self.datasets.all()), 2)

        result = self.datasets.get("processed-001")

        self.assertEqual(
            result.source_raw_dataset_id,
            "raw-001",
        )

        self.assertEqual(
            self.datasets.get("raw-001").content,
            [10.0, 20.0],
        )


if __name__ == "__main__":
    unittest.main()
