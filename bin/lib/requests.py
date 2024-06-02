from dataclasses import dataclass
from .model import *


@dataclass
class CallRequest:
    dir: str
    stdin: str
    stdout: str
    stderr: str
    response_pipe: str
    command: str


@dataclass
class SignalRequest:
    id: int
    signal: SupportedSignal


@dataclass
class ReloadRequest:
    dir: str
    stdin: str
    stdout: str
    stderr: str
    response_pipe: str


Request = None | CallRequest | SignalRequest | ReloadRequest
