from dataclasses import dataclass
from typing import Any, Dict, Protocol

@dataclass
class HapiResponse:
    dataset_id: str
    status: int
    metadata: Dict[str, Any]
    body: str


class IntermagnetSource(Protocol):

    def fetch(
        self,
        parameters: Dict[str, Any],
    ) -> HapiResponse:
        ...
