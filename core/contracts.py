from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.job import JobKind


@dataclass
class ToolResult:
    data: Dict[str, Any]
    dataset_id: Optional[str] = None


class Tool(ABC):
    job_kind: Optional[JobKind] = None

    @abstractmethod
    def validate(self, parameters: Dict[str, Any]) -> None:
        """Check operation parameters before creating a Job."""
        pass

    @abstractmethod
    def execute(
        self,
        parameters: Dict[str, Any],
        job_id: Optional[str] = None,
    ) -> ToolResult:
        """Execute the operation and return its result."""
        pass
