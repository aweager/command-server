import asyncio
import logging
from asyncio import Event, Task
from dataclasses import dataclass
from typing import Self

from jrpc.service import MethodSet, implements, make_method_set
from result import Err, Ok, Result

from command_server.files import FifoCreateFailed, FileOpenFailed

from .api import (
    CancelReloadParams,
    CancelReloadResult,
    ExecutorStatus,
    JobMethod,
    JobStatus,
    ListExecutorsParams,
    ListExecutorsResult,
    ListJobsParams,
    ListJobsResult,
    ReloadExecutorParams,
    ReloadExecutorResult,
    SignalJobParams,
    SignalJobResult,
    StartJobParams,
    StartJobResult,
    StopServerParams,
    StopServerResult,
    WaitForJobParams,
    WaitForJobResult,
    WaitForReloadParams,
    WaitForReloadResult,
)
from .errors import (
    ExecutorAlreadyLoaded,
    ExecutorNotFound,
    ExecutorNotRunning,
    ExecutorReloadActive,
    ExecutorReloadFailed,
    JobApiError,
    JobNotFound,
)
from .executor import Executor, make_executor
from .job import Job
from .server_config import CommandServerConfig

_LOGGER = logging.getLogger("job-impl")


@dataclass
class JobApiImpl:
    config: CommandServerConfig
    stop_event: Event

    def __post_init__(self) -> None:
        self._current_executor: Executor | None = None
        self._reload_lock = asyncio.Lock()
        self._executors: dict[str, Executor] = {}
        self._jobs: dict[str, Job] = {}
        self._next_executor_id: str | None = None
        self._executor_change_task: Task[None] | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        async with asyncio.TaskGroup() as tg:
            for executor in self._executors.values():
                tg.create_task(executor.cleanup(kill_jobs=True))

    async def _try_change_executor(self, executor: Executor) -> None:
        match await executor.wait_ready():
            case Ok():
                self._current_executor = executor
        self._next_executor_id = None

    def check_executor(self) -> Result[Executor, ExecutorNotRunning]:
        if (
            self._current_executor is None
            or self._current_executor.status != ExecutorStatus.RUNNING
        ):
            return Err(ExecutorNotRunning())
        return Ok(self._current_executor)

    @implements(JobMethod.RELOAD_EXECUTOR)
    async def reload_executor(
        self, params: ReloadExecutorParams
    ) -> Result[ReloadExecutorResult, JobApiError]:
        match self.config.base_executor_config.apply_overrides(params.config_overrides):
            case Ok(executor_config):
                pass
            case Err(invalid_config):
                return Err(JobApiError.from_data(invalid_config))

        async with self._reload_lock:
            if self._next_executor_id is not None:
                return Err(JobApiError.from_data(ExecutorReloadActive(self._next_executor_id)))

            match await make_executor(executor_config, params.stdio):
                case Ok(executor):
                    self._executors[executor.id] = executor
                    self._next_executor_id = executor.id
                    self._executor_change_task = asyncio.create_task(
                        self._try_change_executor(executor)
                    )
                    return Ok(ReloadExecutorResult(executor.info))
                case Err(e):
                    self._next_executor_task = None
                    return Err(JobApiError.from_data(e.to_file_error()))

    @implements(JobMethod.CANCEL_RELOAD)
    async def cancel_reload(
        self, params: CancelReloadParams
    ) -> Result[CancelReloadResult, JobApiError]:
        if params.id not in self._executors:
            return Err(JobApiError.from_data(ExecutorNotFound(params.id)))

        executor = self._executors[params.id]
        if executor.status != ExecutorStatus.LOADING:
            return Err(JobApiError.from_data(ExecutorAlreadyLoaded(params.id)))

        await executor.cleanup(signal=params.signal.value)
        return Ok(CancelReloadResult(executor.info))

    @implements(JobMethod.WAIT_FOR_RELOAD)
    async def wait_for_reload(
        self, params: WaitForReloadParams
    ) -> Result[WaitForReloadResult, JobApiError]:
        id = params.id or self._next_executor_id
        if id not in self._executors:
            return Err(JobApiError.from_data(ExecutorNotFound(id)))

        executor = self._executors[id]
        match await executor.wait_ready():
            case Ok():
                return Ok(WaitForReloadResult(executor.info))
            case Err(exit_code):
                return Err(JobApiError.from_data(ExecutorReloadFailed(id, exit_code)))

    @implements(JobMethod.START_JOB)
    async def start_job(self, params: StartJobParams) -> Result[StartJobResult, JobApiError]:
        match self.check_executor():
            case Ok(executor):
                pass
            case Err(not_running):
                return Err(JobApiError.from_data(not_running))

        match await executor.start_job(
            cwd=params.cwd,
            stdio=params.stdio,
            args=params.args,
        ):
            case Ok(job):
                self._jobs[job.id] = job
                return Ok(StartJobResult(job.info))
            case Err(e):
                match e:
                    case FileOpenFailed() | FifoCreateFailed() as file_error:
                        return Err(JobApiError.from_data(file_error.to_file_error()))
                return Err(JobApiError.from_data(e))

    @implements(JobMethod.SIGNAL_JOB)
    async def signal_job(self, params: SignalJobParams) -> Result[SignalJobResult, JobApiError]:
        if params.id not in self._jobs:
            return Err(JobApiError.from_data(JobNotFound(params.id)))

        return Ok(SignalJobResult(self._jobs[params.id].signal(params.signal)))

    @implements(JobMethod.WAIT_FOR_JOB)
    async def wait_for_job(self, params: WaitForJobParams) -> Result[WaitForJobResult, JobApiError]:
        if params.id not in self._jobs:
            return Err(JobApiError.from_data(JobNotFound(params.id)))

        exit_code = await self._jobs[params.id].wait()
        if exit_code is None:
            exit_code = -1
        return Ok(WaitForJobResult(exit_code))

    @implements(JobMethod.STOP_SERVER)
    async def stop_server(self, _: StopServerParams) -> Result[StopServerResult, JobApiError]:
        self.stop_event.set()
        return Ok(StopServerResult())

    @implements(JobMethod.LIST_JOBS)
    async def list_jobs(self, params: ListJobsParams) -> Result[ListJobsResult, JobApiError]:
        if params.include_completed:
            return Ok(ListJobsResult({job.id: job.info for job in self._jobs.values()}))

        return Ok(
            ListJobsResult(
                {job.id: job.info for job in self._jobs.values() if job.status != JobStatus.DONE}
            )
        )

    @implements(JobMethod.LIST_EXECUTORS)
    async def list_executors(
        self, params: ListExecutorsParams
    ) -> Result[ListExecutorsResult, JobApiError]:
        if params.include_closed:
            return Ok(
                ListExecutorsResult(
                    {executor.id: executor.info for executor in self._executors.values()}
                )
            )

        return Ok(
            ListExecutorsResult(
                {
                    executor.id: executor.info
                    for executor in self._executors.values()
                    if executor.status != ExecutorStatus.CLOSED
                }
            )
        )

    def method_set(self) -> MethodSet:
        return make_method_set(JobApiImpl, self)
