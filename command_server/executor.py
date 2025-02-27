import asyncio
import logging
import os
import pathlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from signal import Signals
from typing import Self

from result import Err, Ok, Result

from . import token_io
from .api import ExecutorInfo, ExecutorState, ExecutorStatus, Stdio
from .errors import ExecutorNotRunning, JobStartFailed
from .files import (
    AsyncFileList,
    FifoCreateFailed,
    FileOpenFailed,
    Mode,
    TempFifo,
    mkfifo,
    try_open_multiple,
)
from .job import Job
from .server_config import ExecutorConfig, SignalTranslator
from .token_io import TokenReader, TokenWriter

_LOGGER = logging.getLogger("executor")

os.environ["COMMAND_SERVER_LIB"] = str(Path(__file__).parent.joinpath("lib"))


@dataclass
class ExecutorNeverReady:
    ready_status: int | None


@dataclass
class ExecutorLoadFailed:
    exit_code: int
    cause: FileOpenFailed | ExecutorNeverReady


@dataclass
class Executor:
    id: str
    cwd: pathlib.Path
    command: str
    args: list[str]
    subprocess: asyncio.subprocess.Process
    stdio_files: AsyncFileList
    signal_translator: SignalTranslator
    read_fifo: TempFifo
    write_fifo: TempFifo

    def __post_init__(self) -> None:
        self._reader: TokenReader | None = None
        self._writer: TokenWriter | None = None
        self._jobs: dict[str, Job] = dict()

        self._init_task = asyncio.create_task(self._lazy_init())
        self._teardown_task = asyncio.create_task(self._lazy_teardown())

    @property
    def state(self) -> ExecutorState:
        if self._teardown_task.done():
            return ExecutorState(
                status=ExecutorStatus.CLOSED,
                exit_code=self._teardown_task.result(),
            )

        if self._init_task.done() and self._init_task.result().is_ok():
            return ExecutorState(
                status=ExecutorStatus.RUNNING,
                exit_code=None,
            )

        return ExecutorState(
            status=ExecutorStatus.LOADING,
            exit_code=None,
        )

    @property
    def status(self) -> ExecutorStatus:
        return self.state.status

    @property
    def info(self) -> ExecutorInfo:
        return ExecutorInfo(
            id=self.id,
            cwd=str(self.cwd),
            command=self.command,
            args=self.args,
            state=self.state,
        )

    async def start_job(
        self, cwd: str, args: list[str], stdio: Stdio
    ) -> Result[Job, FifoCreateFailed | FileOpenFailed | ExecutorNotRunning | JobStartFailed]:
        if self.status != ExecutorStatus.RUNNING or self._reader is None or self._writer is None:
            return Err(ExecutorNotRunning())

        match await mkfifo("job_exit"):
            case Ok(exit_fifo):
                pass
            case Err() as err:
                return err

        _LOGGER.info(f"Starting job: {cwd=}, {stdio=}, {exit_fifo.path}, {args=}")

        await self._writer.write(
            [
                str(cwd),
                stdio.stdin,
                stdio.stdout,
                stdio.stderr,
                str(exit_fifo.path),
                str(len(args)),
            ]
            + args
        )

        match await token_io.open_pipe_reader(exit_fifo):
            case Ok(exit_reader):
                pass
            case Err() as err:
                await exit_fifo.unlink()
                return err

        match await self._reader.read_int():
            case Ok(pid):
                pass
            case Err():
                await exit_reader.close()
                return Err(JobStartFailed())

        return Ok(
            Job(
                id=str(uuid.uuid4()),
                executor_id=self.id,
                cwd=cwd,
                pid=pid,
                args=args,
                exit_reader=exit_reader,
                signal_translator=self.signal_translator,
            )
        )

    async def wait_ready(self) -> Result[None, int]:
        await asyncio.wait(
            [self._init_task, self._teardown_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        if self._init_task.done():
            return Ok(None)

        return Err(self._teardown_task.result())

    async def wait_closed(self) -> int:
        return await asyncio.shield(self._teardown_task)

    async def cleanup(self, signal: Signals = Signals.SIGTERM, kill_jobs: bool = False) -> int:
        if self.status != ExecutorStatus.CLOSED:
            self.subprocess.send_signal(signal)

        async with asyncio.TaskGroup() as tg:
            exit_task = tg.create_task(self.wait_closed())
            if kill_jobs:
                for job in self._jobs.values():
                    tg.create_task(job.close())

        return exit_task.result()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.cleanup(kill_jobs=True)

    async def _lazy_init(self) -> Result[None, ExecutorLoadFailed]:
        match await token_io.open_pipe_reader(self.read_fifo):
            case Ok(reader):
                self._reader = reader
            case Err(file_open_error):
                return Err(
                    ExecutorLoadFailed(
                        exit_code=await self.cleanup(),
                        cause=file_open_error,
                    )
                )

        match await token_io.open_pipe_writer(self.write_fifo):
            case Ok(writer):
                self._writer = writer
            case Err(file_open_error):
                return Err(
                    ExecutorLoadFailed(
                        exit_code=await self.cleanup(),
                        cause=file_open_error,
                    )
                )

        ready_status = (await self._reader.read_int()).unwrap_or(None)
        if ready_status == 0:
            return Ok(None)

        return Err(
            ExecutorLoadFailed(
                exit_code=await self.cleanup(),
                cause=ExecutorNeverReady(ready_status),
            )
        )

    async def _lazy_teardown(self) -> int:
        exit_code = await self.subprocess.wait()

        async with asyncio.TaskGroup() as tg:
            if self._writer is not None:
                tg.create_task(self._writer.close())
            if self._reader is not None:
                tg.create_task(self._reader.close())

        return exit_code


async def make_executor(
    config: ExecutorConfig, stdio: Stdio
) -> Result[Executor, FileOpenFailed | FifoCreateFailed]:
    match await try_open_multiple(
        (Path(stdio.stdin), Mode.R), (Path(stdio.stdout), Mode.W), (Path(stdio.stderr), Mode.W)
    ):
        case Ok(stdio_files):
            pass
        case Err() as err:
            return err

    match await mkfifo("executor_reader"):
        case Ok(read_fifo):
            pass
        case Err() as err:
            await stdio_files.close_all()
            return err

    match await mkfifo("executor_writer"):
        case Ok(write_fifo):
            pass
        case Err() as err:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(stdio_files.close_all())
                tg.create_task(read_fifo.unlink())
            return err

    _LOGGER.debug(f"{config.command} {write_fifo.path} {read_fifo.path} {config.args}")

    subprocess = await asyncio.subprocess.create_subprocess_exec(
        config.command,
        str(write_fifo.path),
        str(read_fifo.path),
        *config.args,
        cwd=config.cwd,
        stdin=stdio_files.files[0].fd,
        stdout=stdio_files.files[1].fd,
        stderr=stdio_files.files[2].fd,
    )

    return Ok(
        Executor(
            id=str(uuid.uuid4()),
            cwd=config.cwd,
            command=config.command,
            args=config.args,
            stdio_files=stdio_files,
            signal_translator=config.signal_translator,
            read_fifo=read_fifo,
            write_fifo=write_fifo,
            subprocess=subprocess,
        )
    )
