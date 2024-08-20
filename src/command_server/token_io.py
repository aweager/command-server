from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import os
import socket
import random
from typing import Generator, Optional, Tuple

_HOME = os.getenv("HOME")
_RUNDIR = os.getenv("XDG_RUNTIME_DIR", f"{_HOME}/.cache") + "/command-server"
os.makedirs(_RUNDIR, exist_ok=True)


@contextmanager
def mkfifo(name_hint: str) -> Generator[str, None, None]:
    path = f"{_RUNDIR}/{os.getpid()}.{random.random()}.{name_hint}.pipe"
    try:
        os.mkfifo(path)
        yield path
    finally:
        if path is not None:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass


class Mode(Enum):
    R = 1
    W = 2
    RW = 3

    def to_flag(self) -> int:
        match self:
            case Mode.R:
                return os.O_RDONLY
            case Mode.W:
                return os.O_WRONLY
            case Mode.RW:
                return os.O_RDWR


@contextmanager
def open_fd(path: str, mode: Mode) -> Generator[int, None, None]:
    with open_fds((path, mode)) as fds:
        yield fds[0]


@contextmanager
def open_fds(*args: Tuple[str, Mode]) -> Generator[list[int], None, None]:
    files_to_open: dict[str, int] = dict()
    fds_by_file: dict[str, int] = dict()
    for arg in args:
        if arg[0] not in files_to_open:
            files_to_open[arg[0]] = arg[1].value
        else:
            files_to_open[arg[0]] |= arg[1].value

    try:
        for path, mode_value in files_to_open.items():
            fds_by_file[path] = os.open(path, Mode(mode_value).to_flag())
        yield [fds_by_file[x[0]] for x in args]
    finally:
        for fd in fds_by_file.values():
            os.close(fd)


@dataclass
class _SocketRecvWrapper:
    connection: socket.socket

    def read(self) -> Optional[str]:
        result = self.connection.recv(1024)
        if len(result) == 0:
            return None
        return result.decode()


@dataclass
class _PipeReadWrapper:
    fd: int

    def read(self) -> Optional[str]:
        result = os.read(self.fd, 1024)
        if len(result) == 0:
            return None
        return result.decode()


_ReadWrapper = _SocketRecvWrapper | _PipeReadWrapper


@dataclass
class TokenReader:
    file: _ReadWrapper

    def __post_init__(self) -> None:
        self.completed_tokens: list[str] = []
        self.curr_token: str = ""

    def read(self) -> str:
        """
        Blocking read for a single token, defaulting to empty string
        """
        result = self.read_multiple(1)
        if len(result) == 0:
            return ""
        return result[0]

    def read_multiple(self, num: int) -> list[str]:
        """
        Blocking read for num tokens.

        Buffers completed, escaped tokens into self.completed_tokens until
        there are >= num tokens. Then removes them from the buffer and
        returns them, unescaped.
        """

        while len(self.completed_tokens) < num:
            data_str = self.file.read()
            if data_str:
                self.curr_token += data_str
                data = self.curr_token.split("\n")
                self.completed_tokens += data[0:-1]
                self.curr_token = data[-1]
            else:
                # nothing left to read, return what we have
                result = [self._unescape(x) for x in self.completed_tokens]
                self.completed_tokens = []
                return result

        result = [self._unescape(self.completed_tokens[x]) for x in range(num)]
        self.completed_tokens = self.completed_tokens[num:]
        return result

    def _unescape(self, token: str) -> str:
        """
        Using backslash as the escape character, this method
        unescapes the token in a fairly forgiving way:
            - backslash -> backslash
            - n -> newline
            - end of line -> backslash
            - any other char -> that char
        """

        result = ""
        i = 0
        while i < len(token):
            c = token[i]
            i += 1
            if c != "\\" or i >= len(token):
                result += c
            else:
                c = token[i]
                i += 1
                if c == "n":
                    result += "\n"
                else:
                    result += c
        return result


@contextmanager
def open_pipe_reader(path: str) -> Generator[TokenReader, None, None]:
    with open_fd(path, Mode.R) as fd:
        yield TokenReader(_PipeReadWrapper(fd))


@contextmanager
def accept_connection(server: socket.socket) -> Generator[TokenReader, None, None]:
    with server.accept()[0] as connection:
        yield TokenReader(_SocketRecvWrapper(connection))


@dataclass
class TokenWriter:
    fd: int

    def write(self, tokens: list[str]) -> None:
        """
        Blocking write for a list of tokens.
        """

        data = "\n".join([self._escape(token) for token in tokens]) + "\n"
        os.write(self.fd, data.encode())

    def _escape(self, token: str) -> str:
        """
        Escapes newlines and backslashes.
        """

        return token.replace("\\", "\\\\").replace("\n", "\\n")


@contextmanager
def open_pipe_writer(path: str) -> Generator[TokenWriter, None, None]:
    with open_fd(path, Mode.W) as fd:
        yield TokenWriter(fd)
