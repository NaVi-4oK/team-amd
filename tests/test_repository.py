
import unittest

from concurrent.futures import ThreadPoolExecutor
from core.errors import DomainError
from core.job import JobKind, JobState
from core.repository import InMemoryJobRepository


class TestJobRepository(unittest.TestCase):

    def setUp(self):
        self.repository = InMemoryJobRepository()

    def create_job(
        self,
        key="key-001",
        observatory="ARS",
    ):
        return self.repository.get_or_create(
            operation="import",
            idempotency_key=key,
            parameters={
                "observatory_id": observatory,
            },
            kind=JobKind.IMPORT,
        )

    def test_create_and_get_job(self):
        job, created = self.create_job()

        self.assertTrue(created)
        self.assertEqual(job.state, JobState.CREATED)
        self.assertIs(self.repository.get(job.id), job)

    def test_same_key_returns_same_job(self):
        first, first_created = self.create_job()
        second, second_created = self.create_job()

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertIs(first, second)
        self.assertEqual(len(self.repository.all()), 1)

    def test_same_key_different_parameters(self):
        self.create_job()

        with self.assertRaises(DomainError) as error:
            self.create_job(observatory="HAD")

        self.assertEqual(
            error.exception.code,
            "idempotency_conflict",
        )
        self.assertEqual(len(self.repository.all()), 1)

    def test_different_keys_create_different_jobs(self):
        first, _ = self.create_job(key="key-001")
        second, _ = self.create_job(key="key-002")

        self.assertNotEqual(first.id, second.id)
        self.assertEqual(len(self.repository.all()), 2)

    def test_unknown_job(self):
        with self.assertRaises(DomainError) as error:
            self.repository.get("unknown-id")

        self.assertEqual(
            error.exception.code,
            "job_not_found",
        )

    def test_empty_idempotency_key(self):
        with self.assertRaises(DomainError) as error:
            self.create_job(key="")

        self.assertEqual(
            error.exception.code,
            "invalid_parameters",
        )
        self.assertEqual(
            error.exception.details["field"],
            "idempotency_key",
        )
        self.assertEqual(len(self.repository.all()), 0)

    def test_completed_job_is_not_recreated(self):
        first, _ = self.create_job()

        first.start()
        first.complete("dataset-001")

        second, created = self.create_job()

        self.assertFalse(created)
        self.assertIs(first, second)
        self.assertEqual(second.state, JobState.COMPLETED)

    def test_concurrent_requests_create_one_job(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(
                executor.map(
                    lambda _: self.create_job(),
                    range(20),
                )
            )

        job_ids = {job.id for job, _ in results}
        created_count = sum(
            created for _, created in results
        )

        self.assertEqual(len(job_ids), 1)
        self.assertEqual(created_count, 1)
        self.assertEqual(len(self.repository.all()), 1)


if __name__ == "__main__":
    unittest.main()
