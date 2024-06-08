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
class ReloadRequest:
    args: Stdio


Request = CallRequest | SignalRequest | ReloadRequest
