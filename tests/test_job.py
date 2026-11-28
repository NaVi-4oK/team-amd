import unittest

from core.errors import DomainError
from core.job import Job, JobKind, JobState


class TestJob(unittest.TestCase):

    def test_successful_path(self):
        cases = [
            (JobKind.IMPORT, JobState.DOWNLOADING),
            (JobKind.PROCESS, JobState.PROCESSING),
        ]

        for kind, working_state in cases:
            with self.subTest(kind=kind):
                job = Job(kind)

                self.assertEqual(job.state, JobState.CREATED)

                job.start()
                self.assertEqual(job.state, working_state)

                job.complete("dataset-1")
                self.assertEqual(job.state, JobState.COMPLETED)
                self.assertEqual(job.dataset_id, "dataset-1")

    def assert_rejected(self, job, action):
        previous_state = job.state

        with self.assertRaises(DomainError) as error:
            action()

        self.assertEqual(
            error.exception.code,
            "invalid_job_transition",
        )
        self.assertEqual(job.state, previous_state)

    # З1 — двойная работа
    def test_z1_double_start(self):
        for kind in JobKind:
            with self.subTest(kind=kind):
                job = Job(kind)
                job.start()

                self.assert_rejected(job, job.start)

    # З2 — вечная работа после перезапуска
    def test_z2_interrupted_job(self):
        for kind in JobKind:
            with self.subTest(kind=kind):
                job = Job(kind)
                job.start()
                job.interrupt()

                self.assertEqual(job.state, JobState.FAILED)
                self.assertEqual(
                    job.error.code, "job_interrupted"
                )

                self.assert_rejected(
                    job, lambda: job.complete("dataset-1")
                )

    # З3 — отмена не предусмотрена ADR 0002

    # З4 — два итога
    def test_z4_failed_to_completed(self):
        for kind in JobKind:
            with self.subTest(kind=kind):
                job = Job(kind)
                job.start()
                job.fail(DomainError("test_error", "Failure"))

                self.assert_rejected(
                    job, lambda: job.complete("dataset-1")
                )

    # З5 — успех без работы
    def test_z5_complete_without_start(self):
        for kind in JobKind:
            with self.subTest(kind=kind):
                job = Job(kind)

                self.assert_rejected(
                    job, lambda: job.complete("dataset-1")
                )

    # З6 — повтор успешного задания
    def test_z6_restart_completed(self):
        for kind in JobKind:
            with self.subTest(kind=kind):
                job = Job(kind)
                job.start()
                job.complete("dataset-1")

                self.assert_rejected(job, job.start)

    def test_failure_before_start(self):
        for kind in JobKind:
            with self.subTest(kind=kind):
                job = Job(kind)
                job.fail(DomainError("internal_error", "Failure"))

                self.assertEqual(job.state, JobState.FAILED)
                self.assert_rejected(job, job.start)


if __name__ == "__main__":
    unittest.main()
