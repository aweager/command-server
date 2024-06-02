from dataclasses import dataclass
from enum import Enum
import signal


class SupportedSignal(Enum):
    HUP = signal.SIGHUP
    INT = signal.SIGINT
    QUIT = signal.SIGQUIT
    TERM = signal.SIGTERM


@dataclass
class WorkItem:
    id: int
    dir: str
    stdin: str
    stdout: str
    stderr: str
    response_pipe: str
    command: str
