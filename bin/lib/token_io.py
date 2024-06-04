import os
import socket
from typing import Optional


class _SocketRecvWrapper:
    connection: socket.socket
    is_open: bool

    def __init__(self, server: socket.socket) -> None:
        self.connection, _ = server.accept()
        self.is_open = True

    def close(self) -> None:
        if self.is_open:
            self.connection.close()
            self.is_open = False

    def read(self) -> Optional[str]:
        if not self.is_open:
            raise RuntimeError("Socket reader was closed")

        result = self.connection.recv(1024)
        if len(result) == 0:
            return None
        return result.decode()


class _PipeReadWrapper:
    fd: int
    is_open: bool

    def __init__(self, fifo_path: str) -> None:
        self.fd = os.open(fifo_path, os.O_RDONLY)
        self.is_open = True

    def close(self):
        if self.is_open:
            os.close(self.fd)
            self.is_open = False

    def read(self) -> Optional[str]:
        if not self.is_open:
            raise RuntimeError("Pipe reader was closed")

        result = os.read(self.fd, 1024)
        if len(result) == 0:
            return None
        return result.decode()


_ReadWrapper = _SocketRecvWrapper | _PipeReadWrapper


class TokenReader:
    file: _ReadWrapper

    completed_tokens: list[str]
    curr_token: str

    def __init__(self, file: _ReadWrapper) -> None:
        self.file = file

        self.completed_tokens = []
        self.curr_token = ""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self) -> None:
        self.file.close()

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


def open_pipe_reader(path: str) -> TokenReader:
    return TokenReader(_PipeReadWrapper(path))


def accept_connection(server: socket.socket) -> TokenReader:
    return TokenReader(_SocketRecvWrapper(server))


class TokenWriter:
    fd: int
    is_open: bool

    def __init__(self, path: str) -> None:
        self.fd = os.open(path, os.O_WRONLY)
        self.is_open = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self) -> None:
        if self.is_open:
            os.close(self.fd)
            self.is_open = False

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


def open_pipe_writer(path: str) -> TokenWriter:
    return TokenWriter(path)
