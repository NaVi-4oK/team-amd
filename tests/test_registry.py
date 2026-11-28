import unittest

from core.contracts import Tool, ToolResult
from core.errors import DomainError
from core.registry import Registry


class FakeTool(Tool):
    def validate(self, parameters):
        pass

    def execute(self, parameters, job_id=None):
        return ToolResult(data={"success": True})


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = Registry()

    def test_register_and_get(self):
        tool = FakeTool()

        self.registry.register("test", tool)

        self.assertIs(self.registry.get("test"), tool)

    def test_unknown_operation(self):
        with self.assertRaises(DomainError) as error:
            self.registry.get("unknown")

        self.assertEqual(
            error.exception.code,
            "unknown_operation",
        )

    def test_duplicate_operation(self):
        original = FakeTool()

        self.registry.register("test", original)

        with self.assertRaises(DomainError) as error:
            self.registry.register("test", FakeTool())

        self.assertEqual(
            error.exception.code,
            "operation_already_registered",
        )

        self.assertIs(
            self.registry.get("test"),
            original,
        )

    def test_invalid_operation_name(self):
        with self.assertRaises(DomainError) as error:
            self.registry.register("", FakeTool())

        self.assertEqual(
            error.exception.code,
            "invalid_parameters",
        )
        self.assertEqual(
            error.exception.details["field"],
            "operation",
        )

    def test_operations_list(self):
        self.registry.register("import", FakeTool())
        self.registry.register("process", FakeTool())
        self.registry.register("query", FakeTool())

        self.assertEqual(
            self.registry.operations(),
            ["import", "process", "query"],
        )


if __name__ == "__main__":
    unittest.main()
