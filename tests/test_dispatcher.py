
import unittest

from concurrent.futures import ThreadPoolExecutor
from core.contracts import Tool, ToolResult
from core.dispatcher import Dispatcher
from core.errors import DomainError
from core.job import JobKind, JobState
from core.registry import Registry
from core.repository import InMemoryJobRepository


class FakeTool(Tool):

    def __init__(
        self,
        job_kind=JobKind.IMPORT,
        error=None,
    ):
        self.job_kind = job_kind
        self.error = error
        self.calls = 0

    def validate(self, parameters):
        if not parameters.get("value"):
            raise DomainError(
                "invalid_parameters",
                "Value is required",
                {"field": "value"},
            )

    def execute(self, parameters, job_id=None):
        self.calls += 1

        if self.error is not None:
            raise self.error

        return ToolResult(
            data={
                "value": parameters["value"],
                "job_id": job_id,
            },
            dataset_id="dataset-001",
        )


class TestDispatcher(unittest.TestCase):

    def setUp(self):
        self.registry = Registry()
        self.repository = InMemoryJobRepository()

        self.dispatcher = Dispatcher(
            self.registry,
            self.repository,
        )

    def test_successful_job(self):
        for kind in JobKind:
            with self.subTest(kind=kind):
                operation = kind.value
                tool = FakeTool(job_kind=kind)

                self.registry.register(operation, tool)

                job = self.dispatcher.dispatch(
                    operation,
                    {"value": "test"},
                    f"key-{operation}",
                )

                self.assertEqual(
                    job.state, JobState.COMPLETED
                )
                self.assertEqual(
                    job.dataset_id, "dataset-001"
                )
                self.assertEqual(tool.calls, 1)
                self.assertIs(
                    self.dispatcher.get_job(job.id),
                    job,
                )

    def test_unknown_operation(self):
        with self.assertRaises(DomainError) as error:
            self.dispatcher.dispatch(
                "unknown",
                {},
                "key-001",
            )

        self.assertEqual(
            error.exception.code,
            "unknown_operation",
        )
        self.assertEqual(len(self.repository.all()), 0)

    def test_invalid_parameters(self):
        tool = FakeTool()
        self.registry.register("import", tool)

        with self.assertRaises(DomainError) as error:
            self.dispatcher.dispatch(
                "import",
                {},
                "key-001",
            )

        self.assertEqual(
            error.exception.code,
            "invalid_parameters",
        )
        self.assertEqual(
            error.exception.details["field"],
            "value",
        )
        self.assertEqual(tool.calls, 0)
        self.assertEqual(len(self.repository.all()), 0)

    def test_tool_domain_error(self):
        tool = FakeTool(
            error=DomainError(
                "storage_error",
                "Unable to save dataset",
            )
        )

        self.registry.register("import", tool)

        job = self.dispatcher.dispatch(
            "import",
            {"value": "test"},
            "key-001",
        )

        self.assertEqual(job.state, JobState.FAILED)
        self.assertEqual(job.error.code, "storage_error")
        self.assertIsNone(job.dataset_id)

    def test_unexpected_tool_exception(self):
        tool = FakeTool(
            error=RuntimeError("Unexpected failure")
        )

        self.registry.register("import", tool)

        job = self.dispatcher.dispatch(
            "import",
            {"value": "test"},
            "key-001",
        )

        self.assertEqual(job.state, JobState.FAILED)
        self.assertEqual(job.error.code, "internal_error")
        self.assertIsNone(job.dataset_id)

    def test_idempotent_execution(self):
        tool = FakeTool()
        self.registry.register("import", tool)

        first = self.dispatcher.dispatch(
            "import",
            {"value": "test"},
            "key-001",
        )

        second = self.dispatcher.dispatch(
            "import",
            {"value": "test"},
            "key-001",
        )

        self.assertIs(first, second)
        self.assertEqual(tool.calls, 1)
        self.assertEqual(len(self.repository.all()), 1)

    def test_idempotency_conflict(self):
        tool = FakeTool()
        self.registry.register("import", tool)

        self.dispatcher.dispatch(
            "import",
            {"value": "first"},
            "key-001",
        )

        with self.assertRaises(DomainError) as error:
            self.dispatcher.dispatch(
                "import",
                {"value": "second"},
                "key-001",
            )

        self.assertEqual(
            error.exception.code,
            "idempotency_conflict",
        )
        self.assertEqual(tool.calls, 1)

    def test_query_without_job(self):
        tool = FakeTool(job_kind=None)
        self.registry.register("query", tool)

        result = self.dispatcher.dispatch(
            "query",
            {"value": "test"},
        )

        self.assertIsInstance(result, ToolResult)
        self.assertEqual(result.data["value"], "test")
        self.assertIsNone(result.data["job_id"])
        self.assertEqual(len(self.repository.all()), 0)

    def test_recover_interrupted_jobs(self):
        job, _ = self.repository.get_or_create(
            operation="import",
            idempotency_key="key-001",
            parameters={"value": "test"},
            kind=JobKind.IMPORT,
        )

        job.start()

        recovered = (
            self.dispatcher.recover_interrupted_jobs()
        )

        self.assertEqual(recovered, 1)
        self.assertEqual(job.state, JobState.FAILED)
        self.assertEqual(
            job.error.code,
            "job_interrupted",
        )

        self.assertEqual(
            self.dispatcher.recover_interrupted_jobs(),
            0,
        )

    def test_background_execution(self):
        tool = FakeTool()
        self.registry.register("import", tool)

        with ThreadPoolExecutor(max_workers=2) as executor:
            dispatcher = Dispatcher(
                self.registry,
                self.repository,
                executor=executor,
            )

            job = dispatcher.dispatch(
                "import",
                {"value": "test"},
                "key-001",
            )

        self.assertEqual(job.state, JobState.COMPLETED)
        self.assertEqual(tool.calls, 1)


if __name__ == "__main__":
    unittest.main()
