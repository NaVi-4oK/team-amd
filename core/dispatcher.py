
from copy import deepcopy
from typing import Any, Dict, Optional, Union

from core.contracts import Tool, ToolResult
from core.errors import DomainError
from core.job import Job, JobState
from core.registry import Registry
from core.repository import JobRepository


class Dispatcher:

    def __init__(
        self,
        registry: Registry,
        repository: JobRepository,
        executor=None,
    ):
        self._registry = registry
        self._repository = repository
        self._executor = executor

    def dispatch(
        self,
        operation: str,
        parameters: Dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> Union[Job, ToolResult]:

        tool = self._registry.get(operation)

        if not isinstance(parameters, dict):
            raise DomainError(
                "invalid_parameters",
                "Parameters must be an object",
                {"field": "parameters"},
            )

        parameters = deepcopy(parameters)

        tool.validate(parameters)

        # Synchronous operation without Job
        if tool.job_kind is None:
            try:
                result = tool.execute(parameters)

                if not isinstance(result, ToolResult):
                    raise DomainError(
                        "internal_error",
                        "Tool returned an invalid result",
                    )

                return result

            except DomainError:
                raise

            except Exception:
                raise DomainError(
                    "internal_error",
                    "Tool execution failed",
                ) from None

        # Operation with Job
        job, created = self._repository.get_or_create(
            operation=operation,
            idempotency_key=idempotency_key,
            parameters=parameters,
            kind=tool.job_kind,
        )

        if not created:
            return job

        if self._executor is None:
            self._execute_job(job, tool, parameters)
        else:
            try:
                self._executor.submit(
                    self._execute_job,
                    job,
                    tool,
                    parameters,
                )
            except Exception:
                job.fail(
                    DomainError(
                        "internal_error",
                        "Unable to schedule Job",
                    )
                )

        return job

    def _execute_job(
        self,
        job: Job,
        tool: Tool,
        parameters: Dict[str, Any],
    ) -> None:

        job.start()

        try:
            result = tool.execute(
                parameters,
                job_id=job.id,
            )

            if (
                not isinstance(result, ToolResult)
                or not isinstance(result.dataset_id, str)
                or not result.dataset_id.strip()
            ):
                raise DomainError(
                    "internal_error",
                    "Tool returned no valid dataset ID",
                )

            job.complete(result.dataset_id)

        except DomainError as error:
            job.fail(error)

        except Exception:
            job.fail(
                DomainError(
                    "internal_error",
                    "Tool execution failed",
                )
            )

    def get_job(self, job_id: str) -> Job:
        return self._repository.get(job_id)

    def recover_interrupted_jobs(self) -> int:
        recovered = 0

        for job in self._repository.all():
            if job.state in {
                JobState.DOWNLOADING,
                JobState.PROCESSING,
            }:
                job.interrupt()
                recovered += 1

        return recovered
