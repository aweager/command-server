from dataclasses import dataclass
from .model import *


@dataclass
class CallRequest:
    dir: str
    stdio: Stdio
    command: list[str]


@dataclass
class SignalRequest:
    id: int
    signal: SupportedSignal


@dataclass
class StatusRequest:
    stdio: Stdio


@dataclass
class ReloadRequest:
    args: Stdio


@dataclass
class TerminateRequest:
    pass


Request = CallRequest | SignalRequest | StatusRequest | ReloadRequest | TerminateRequest
