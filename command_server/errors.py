from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import IntEnum, StrEnum, auto
from functools import partial
from typing import Any, TypeVar

from dataclasses_json import DataClassJsonMixin
from dataclasses_json.mm import SchemaType
from jrpc.data import JsonRpcError, JsonTryLoadMixin, ParsedJson
from jrpc.service import BidirectionalConverter
from typing_extensions import override


class JobApiErrorCode(IntEnum):
    JOB_NOT_FOUND = 33001
    EXECUTOR_NOT_FOUND = 33002
    EXECUTOR_ALREADY_LOADED = 33003
    EXECUTOR_RELOAD_ACTIVE = 33004
    EXECUTOR_RELOAD_FAILED = 33005
    EXECUTOR_NOT_RUNNING = 33006
    FILE_ERROR = 33007
    JOB_START_FAILED = 33008
    INVALID_EXECUTOR_CONFIG = 33009


_registry_by_code: dict[int, Callable[[ParsedJson], Any]] = {}
_registry_by_type: dict[type[DataClassJsonMixin], tuple[int, str]] = {}

_T = TypeVar("_T")


def _load_if_dict(schema: SchemaType[_T], parsed_json: ParsedJson) -> _T | None:
    if not isinstance(parsed_json, Mapping):
        return None
    if not isinstance(parsed_json, dict):
        parsed_json = dict(parsed_json)

    try:
        return schema.load(parsed_json, unknown="exclude")
    except ValueError:
        # Swallow error load issues
        return None


def register_error_type(code: int, message: str, data_type: type[DataClassJsonMixin]) -> None:
    _registry_by_code[code] = partial(_load_if_dict, data_type.schema())
    _registry_by_type[data_type] = (code, message)


@dataclass
class JobApiError:
    code: int
    message: str
    raw_data: ParsedJson

    def __post_init__(self) -> None:
        if self.code in _registry_by_code:
            self.data = _registry_by_code[self.code](self.raw_data)
        else:
            self.data = None

    def to_json_rpc_error(self) -> JsonRpcError:
        return JsonRpcError(self.code, self.message, self.raw_data)

    @staticmethod
    def from_json_rpc_error(error: JsonRpcError) -> "JobApiError":
        return JobApiError(error.code, error.message, error.data)

    @staticmethod
    def from_data(data: DataClassJsonMixin) -> "JobApiError":
        if type(data) not in _registry_by_type:
            raise ValueError()
        code, message = _registry_by_type[type(data)]
        return JobApiError(code, message, data.to_dict())


class JobApiErrorConverter(BidirectionalConverter[JsonRpcError, JobApiError]):
    @override
    def load(self, f: JsonRpcError) -> JobApiError:
        return JobApiError.from_json_rpc_error(f)

    @override
    def dump(self, t: JobApiError) -> JsonRpcError:
        return t.to_json_rpc_error()


ERROR_CONVERTER = JobApiErrorConverter()


@dataclass
class JobNotFound(JsonTryLoadMixin):
    id: str


register_error_type(
    JobApiErrorCode.JOB_NOT_FOUND,
    "Job not found",
    JobNotFound,
)


@dataclass
class ExecutorNotFound(JsonTryLoadMixin):
    id: str | None


register_error_type(
    JobApiErrorCode.EXECUTOR_NOT_FOUND,
    "Executor not found",
    ExecutorNotFound,
)


@dataclass
class ExecutorAlreadyLoaded(JsonTryLoadMixin):
    id: str


register_error_type(
    JobApiErrorCode.EXECUTOR_ALREADY_LOADED,
    "Executor is already loaded",
    ExecutorAlreadyLoaded,
)


@dataclass
class ExecutorReloadActive(JsonTryLoadMixin):
    id: str


register_error_type(
    JobApiErrorCode.EXECUTOR_RELOAD_ACTIVE,
    "Executor is currently being reloaded",
    ExecutorReloadActive,
)


@dataclass
class ExecutorReloadFailed(JsonTryLoadMixin):
    id: str
    exit_code: int


register_error_type(
    JobApiErrorCode.EXECUTOR_RELOAD_FAILED,
    "Executor reload failed",
    ExecutorReloadFailed,
)


@dataclass
class ExecutorNotRunning(JsonTryLoadMixin):
    pass


register_error_type(
    JobApiErrorCode.EXECUTOR_NOT_RUNNING,
    "No executor is currently running",
    ExecutorNotRunning,
)


class FileErrorType(StrEnum):
    CREATE_FAILED = auto()
    OPEN_FAILED = auto()


@dataclass
class FileError(JsonTryLoadMixin):
    type: FileErrorType
    path: str
    detailed_message: str


register_error_type(
    JobApiErrorCode.FILE_ERROR,
    "A file system error occurred",
    FileError,
)


@dataclass
class JobStartFailed(JsonTryLoadMixin):
    pass


register_error_type(
    JobApiErrorCode.JOB_START_FAILED,
    "An error occurred starting the job",
    JobStartFailed,
)


@dataclass
class InvalidExecutorConfig(JsonTryLoadMixin):
    detailed_message: str


register_error_type(
    JobApiErrorCode.INVALID_EXECUTOR_CONFIG,
    "Executor config was invalid",
    InvalidExecutorConfig,
)
