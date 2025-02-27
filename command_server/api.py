from dataclasses import dataclass, field
from enum import Enum, StrEnum, auto
from signal import Signals

from dataclasses_json import config
from jrpc.data import JsonTryLoadMixin
from jrpc.service import JsonTryConverter, MethodDescriptor
from marshmallow import fields

from .errors import ERROR_CONVERTER


@dataclass
class Stdio(JsonTryLoadMixin):
    stdin: str
    stdout: str
    stderr: str


class Signal(Enum):
    TERM = Signals.SIGTERM
    INT = Signals.SIGINT
    HUP = Signals.SIGHUP
    QUIT = Signals.SIGQUIT


class ExecutorStatus(StrEnum):
    LOADING = auto()
    RUNNING = auto()
    CLOSED = auto()


@dataclass
class ExecutorState(JsonTryLoadMixin):
    status: ExecutorStatus = field(
        metadata=config(mm_field=fields.Enum(ExecutorStatus, by_value=False))
    )
    exit_code: int | None


@dataclass
class ExecutorInfo(JsonTryLoadMixin):
    id: str
    cwd: str
    command: str
    args: list[str]
    state: ExecutorState


class JobStatus(StrEnum):
    RUNNING = auto()
    DONE = auto()


@dataclass
class JobState(JsonTryLoadMixin):
    status: JobStatus = field(metadata=config(mm_field=fields.Enum(JobStatus)))
    exit_code: int | None


@dataclass
class JobInfo(JsonTryLoadMixin):
    id: str
    executor_id: str
    cwd: str
    args: list[str]
    state: JobState


@dataclass
class ExecutorConfigOverrides(JsonTryLoadMixin):
    cwd: str | None = None
    args: list[str] | None = None


@dataclass
class ReloadExecutorParams(JsonTryLoadMixin):
    stdio: Stdio
    config_overrides: ExecutorConfigOverrides


@dataclass
class ReloadExecutorResult(JsonTryLoadMixin):
    executor: ExecutorInfo


@dataclass
class CancelReloadParams(JsonTryLoadMixin):
    id: str
    signal: Signal = field(metadata=config(mm_field=fields.Enum(Signal)))


@dataclass
class CancelReloadResult(JsonTryLoadMixin):
    executor: ExecutorInfo


@dataclass
class WaitForReloadParams(JsonTryLoadMixin):
    id: str | None


@dataclass
class WaitForReloadResult(JsonTryLoadMixin):
    executor: ExecutorInfo


@dataclass
class StartJobParams(JsonTryLoadMixin):
    cwd: str
    args: list[str]
    stdio: Stdio


@dataclass
class StartJobResult(JsonTryLoadMixin):
    job: JobInfo


@dataclass
class SignalJobParams(JsonTryLoadMixin):
    id: str
    signal: Signal = field(metadata=config(mm_field=fields.Enum(Signal)))


@dataclass
class SignalJobResult(JsonTryLoadMixin):
    actual_signal: Signal = field(metadata=config(mm_field=fields.Enum(Signal)))


@dataclass
class WaitForJobParams(JsonTryLoadMixin):
    id: str


@dataclass
class WaitForJobResult(JsonTryLoadMixin):
    exit_code: int


@dataclass
class StopServerParams(JsonTryLoadMixin):
    pass


@dataclass
class StopServerResult(JsonTryLoadMixin):
    pass


@dataclass
class ListJobsParams(JsonTryLoadMixin):
    include_completed: bool


@dataclass
class ListJobsResult(JsonTryLoadMixin):
    jobs: dict[str, JobInfo]


@dataclass
class ListExecutorsParams(JsonTryLoadMixin):
    include_closed: bool


@dataclass
class ListExecutorsResult(JsonTryLoadMixin):
    executors: dict[str, ExecutorInfo]


class JobMethod:
    START_JOB = MethodDescriptor(
        name="job.start",
        params_converter=JsonTryConverter(StartJobParams),
        result_converter=JsonTryConverter(StartJobResult),
        error_converter=ERROR_CONVERTER,
    )
    SIGNAL_JOB = MethodDescriptor(
        name="job.signal",
        params_converter=JsonTryConverter(SignalJobParams),
        result_converter=JsonTryConverter(SignalJobResult),
        error_converter=ERROR_CONVERTER,
    )
    WAIT_FOR_JOB = MethodDescriptor(
        name="job.wait",
        params_converter=JsonTryConverter(WaitForJobParams),
        result_converter=JsonTryConverter(WaitForJobResult),
        error_converter=ERROR_CONVERTER,
    )

    RELOAD_EXECUTOR = MethodDescriptor(
        name="executor.reload",
        params_converter=JsonTryConverter(ReloadExecutorParams),
        result_converter=JsonTryConverter(ReloadExecutorResult),
        error_converter=ERROR_CONVERTER,
    )
    CANCEL_RELOAD = MethodDescriptor(
        name="executor.cancel-reload",
        params_converter=JsonTryConverter(CancelReloadParams),
        result_converter=JsonTryConverter(CancelReloadResult),
        error_converter=ERROR_CONVERTER,
    )
    WAIT_FOR_RELOAD = MethodDescriptor(
        name="executor.wait-ready",
        params_converter=JsonTryConverter(WaitForReloadParams),
        result_converter=JsonTryConverter(WaitForReloadResult),
        error_converter=ERROR_CONVERTER,
    )

    STOP_SERVER = MethodDescriptor(
        name="command_server.stop",
        params_converter=JsonTryConverter(StopServerParams),
        result_converter=JsonTryConverter(StopServerResult),
        error_converter=ERROR_CONVERTER,
    )
    LIST_JOBS = MethodDescriptor(
        name="command_server.list-jobs",
        params_converter=JsonTryConverter(ListJobsParams),
        result_converter=JsonTryConverter(ListJobsResult),
        error_converter=ERROR_CONVERTER,
    )
    LIST_EXECUTORS = MethodDescriptor(
        name="command_server.list-executors",
        params_converter=JsonTryConverter(ListExecutorsParams),
        result_converter=JsonTryConverter(ListExecutorsResult),
        error_converter=ERROR_CONVERTER,
    )
