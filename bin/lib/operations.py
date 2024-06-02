from dataclasses import dataclass

from .model import SupportedSignal


@dataclass
class AddWorkItem:
    id: int


@dataclass
class CompleteWorkItem:
    id: int


@dataclass
class SignalWorkItem:
    id: int
    signal: SupportedSignal


@dataclass
class ReloadExecutor:
    dir: str
    stdin: str
    stdout: str
    stderr: str
    response_pipe: str


Operation = AddWorkItem | CompleteWorkItem | SignalWorkItem | ReloadExecutor
