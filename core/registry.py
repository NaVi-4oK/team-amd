from typing import Dict
from core.contracts import Tool
from core.errors import DomainError


class Registry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, operation: str, tool: Tool):
        if not isinstance(operation, str) or not operation.strip():
            raise DomainError(
                "invalid_parameters",
                "Operation name is required",
                {"field": "operation"},
            )

        if operation in self._tools:
            raise DomainError(
                "operation_already_registered",
                f"Operation '{operation}' is already registered",
                {"operation": operation},
            )

        self._tools[operation] = tool

    def get(self, operation: str) -> Tool:
        if operation not in self._tools:
            raise DomainError(
                "unknown_operation",
                f"Unknown operation: {operation}",
                {"operation": operation},
            )

        return self._tools[operation]

    def operations(self):
        return sorted(self._tools.keys())
