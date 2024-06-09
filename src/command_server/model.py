from dataclasses import dataclass
from enum import Enum
import signal


class SupportedSignal(Enum):
    HUP = signal.SIGHUP.value
    INT = signal.SIGINT.value
    QUIT = signal.SIGQUIT.value
    TERM = signal.SIGTERM.value


@dataclass
class Stdio:
    stdin: str
    stdout: str
    stderr: str
    status_pipe: str


@dataclass
class WorkItem:
    id: int
    dir: str
    stdio: Stdio
    command: list[str]
