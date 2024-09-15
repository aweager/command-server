import asyncio
import enum
import logging
import os
import pathlib
import random
from dataclasses import dataclass
from typing import Literal, Self

from result import Err, Ok, Result

from command_server.errors import FileError, FileErrorType

_LOGGER = logging.getLogger("files")

_HOME = os.getenv("HOME")
_RUNDIR = os.getenv("XDG_RUNTIME_DIR", f"{_HOME}/.cache") + "/command-server"
os.makedirs(_RUNDIR, exist_ok=True)


@dataclass
class FifoCreateFailed:
    path: pathlib.Path
    exception: Exception

    def to_file_error(self) -> FileError:
        return FileError(FileErrorType.CREATE_FAILED, str(self.path), repr(self.exception))


@dataclass
class FileOpenFailed:
    path: pathlib.Path
    exception: Exception

    def to_file_error(self) -> FileError:
        return FileError(FileErrorType.OPEN_FAILED, str(self.path), repr(self.exception))


class TempFifo:
    path: pathlib.Path
    deleted: bool

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.deleted = False

    async def unlink(self) -> None:
        if not self.deleted:
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None,
                    os.unlink,
                    self.path,
                )
            except FileNotFoundError:
                pass
            self.deleted = True

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, type, value, tb) -> None:
        await self.unlink()


async def mkfifo(name_hint: str) -> Result[TempFifo, FifoCreateFailed]:
    path = pathlib.Path(f"{_RUNDIR}/{os.getpid()}.{random.random()}.{name_hint}.pipe")
    try:
        await asyncio.get_running_loop().run_in_executor(
            None,
            os.mkfifo,
            path,
        )
        _LOGGER.debug(f"Made fifo {path}")
        return Ok(TempFifo(path))

    except Exception as mkfifo_exception:
        try:
            await asyncio.get_running_loop().run_in_executor(
                None,
                os.unlink,
                path,
            )
        except FileNotFoundError:
            pass
        except Exception as unlink_exception:
            _LOGGER.error(f"Could not unlink fifo {path}", exc_info=unlink_exception)

        return Err(FifoCreateFailed(path, mkfifo_exception))


@dataclass
class AsyncFile:
    fd: int

    def __post_init__(self) -> None:
        self._close_future: asyncio.Future[None] | None = None

    async def read(self, length: int = 2048) -> bytes:
        return await asyncio.get_running_loop().run_in_executor(
            None,
            os.read,
            self.fd,
            length,
        )

    async def write(self, data: bytes) -> int:
        return await asyncio.get_running_loop().run_in_executor(
            None,
            os.write,
            self.fd,
            data,
        )

    async def close(self) -> None:
        if self._close_future is None:
            self._close_future = asyncio.get_running_loop().run_in_executor(
                None,
                os.close,
                self.fd,
            )
        await self._close_future

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()


class Mode(enum.Flag):
    R = 1
    W = 2

    def to_flag(self) -> int:
        rw = Mode.R | Mode.W
        match self:
            case Mode.R:
                return os.O_RDONLY
            case Mode.W:
                return os.O_WRONLY
            case _:
                return os.O_RDWR

    def to_str(self) -> Literal["rb", "wb", "r+b"]:
        match self:
            case Mode.R:
                return "rb"
            case Mode.W:
                return "wb"
            case _:
                return "r+b"


async def try_open(path: pathlib.Path, mode: Mode) -> Result[AsyncFile, FileOpenFailed]:
    try:
        fd = await asyncio.get_running_loop().run_in_executor(
            None,
            os.open,
            path,
            mode.to_flag(),
        )
        return Ok(AsyncFile(fd))
    except Exception as open_exception:
        _LOGGER.error(f"Failed to open file {path} in {mode}: {open_exception}")
        return Err(FileOpenFailed(path, open_exception))


class AsyncFileList:
    files: list[AsyncFile]

    def __init__(self, files: list[AsyncFile] = []) -> None:
        self.files = files

    async def close_all(self) -> None:
        files = self.files
        self.files = []
        async with asyncio.TaskGroup() as tg:
            for file in files:
                tg.create_task(file.close())

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, type, value, tb) -> None:
        await self.close_all()


async def try_open_multiple(
    *args: tuple[pathlib.Path, Mode]
) -> Result[AsyncFileList, FileOpenFailed]:
    mode_by_path: dict[pathlib.Path, Mode] = dict()
    for arg in args:
        if arg[0] not in mode_by_path:
            mode_by_path[arg[0]] = arg[1]
        else:
            mode_by_path[arg[0]] |= arg[1]

    file_by_path: dict[pathlib.Path, AsyncFile] = dict()
    for path, mode in mode_by_path.items():
        match await try_open(path, mode):
            case Ok(file):
                file_by_path[path] = file
            case Err() as err:
                await AsyncFileList(list(file_by_path.values())).close_all()
                return err

    return Ok(AsyncFileList([file_by_path[arg[0]] for arg in args]))
