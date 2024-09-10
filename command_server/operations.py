from dataclasses import dataclass

from .model import Stdio, SupportedSignal, WorkItem


@dataclass
class AddWorkItem:
    work_item: WorkItem


@dataclass
class CompleteWorkItem:
    id: int


@dataclass
class SignalWorkItem:
    id: int
    signal: SupportedSignal


@dataclass
class DisplayStatus:
    stdio: Stdio


@dataclass
class ReloadExecutor:
    stdio: Stdio


@dataclass
class TerminateServer:
    pass


Operation = (
    AddWorkItem
    | CompleteWorkItem
    | SignalWorkItem
    | DisplayStatus
    | ReloadExecutor
    | TerminateServer
)
