from dataclasses import dataclass

from .model import Stdio, SupportedSignal


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
    stdio: Stdio


@dataclass
class TerminateServer:
    pass


Operation = (
    AddWorkItem | CompleteWorkItem | SignalWorkItem | ReloadExecutor | TerminateServer
)
