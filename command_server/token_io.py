import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Self

from result import Err, Ok, Result

from .files import AsyncFile, FileOpenFailed, Mode, TempFifo, try_open

_LOGGER = logging.getLogger("token-io")

_HOME = os.getenv("HOME")
_RUNDIR = os.getenv("XDG_RUNTIME_DIR", f"{_HOME}/.cache") + "/command-server"
os.makedirs(_RUNDIR, exist_ok=True)


@dataclass
class TokenReader:
    fifo: TempFifo
    file: AsyncFile

    def __post_init__(self) -> None:
        self._buffer: str = ""

    async def read(self) -> str:
        """
        Blocking read for a single token, defaulting to empty string
        """

        newline_ind = self._buffer.find("\n")
        while newline_ind < 0:
            chunk = await self.file.read()
            if chunk:
                self._buffer += chunk.decode()
                newline_ind = self._buffer.find("\n")
            else:
                # nothing left to read, return what we have
                result = self._unescape(self._buffer)
                self._buffer = ""
                return result

        result = self._unescape(self._buffer[0:newline_ind])
        self._buffer = self._buffer[newline_ind + 1 :]
        return result

    async def read_int(self) -> Result[int, str]:
        token = await self.read()
        try:
            return Ok(int(token))
        except ValueError:
            return Err(token)

    async def close(self) -> None:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.file.close())
            tg.create_task(self.fifo.unlink())

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, type, value, tb) -> None:
        await self.close()

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


async def open_pipe_reader(fifo: TempFifo) -> Result[TokenReader, FileOpenFailed]:
    _LOGGER.debug(f"Opening {fifo.path=} for reading")
    return (await try_open(fifo.path, Mode.R)).map(lambda f: TokenReader(fifo, f))


@dataclass
class TokenWriter:
    fifo: TempFifo
    file: AsyncFile

    async def write(self, tokens: list[str]) -> None:
        """
        Blocking write for a list of tokens.
        """

        _LOGGER.debug(f"Writing {tokens=}")

        data_str = "\n".join([self._escape(token) for token in tokens]) + "\n"
        await self.file.write(data_str.encode())

    async def close(self) -> None:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.file.close())
            tg.create_task(self.fifo.unlink())

    def _escape(self, token: str) -> str:
        """
        Escapes newlines and backslashes.
        """

        return token.replace("\\", "\\\\").replace("\n", "\\n")

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, type, value, tb) -> None:
        await self.close()


async def open_pipe_writer(fifo: TempFifo) -> Result[TokenWriter, FileOpenFailed]:
    _LOGGER.debug(f"Opening {fifo.path=} for writing")
    return (await try_open(fifo.path, Mode.W)).map(lambda f: TokenWriter(fifo, f))
