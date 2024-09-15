import asyncio
import os
from dataclasses import dataclass
from typing import Self

from .api import JobInfo, JobState, JobStatus, Signal
from .server_config import SignalTranslator
from .token_io import TokenReader


@dataclass
class Job:
    id: str
    executor_id: str
    pid: int
    cwd: str
    args: list[str]
    signal_translator: SignalTranslator
    exit_reader: TokenReader

    def __post_init__(self) -> None:
        self._exit_task = asyncio.create_task(self.exit_reader.read_int())

    @property
    def state(self) -> JobState:
        if self._exit_task.done():
            return JobState(
                status=JobStatus.DONE,
                exit_code=self._exit_task.result().unwrap_or(None),
            )

        return JobState(
            status=JobStatus.RUNNING,
            exit_code=None,
        )

    @property
    def status(self) -> JobStatus:
        return self.state.status

    @property
    def info(self) -> JobInfo:
        return JobInfo(
            id=self.id,
            executor_id=self.executor_id,
            cwd=self.cwd,
            args=self.args,
            state=self.state,
        )

    async def wait(self) -> int | None:
        result = await asyncio.shield(self._exit_task)
        return result.unwrap_or(None)

    def signal(self, sig: Signal) -> Signal:
        actual_signal = self.signal_translator.translate(sig)
        os.kill(self.pid, actual_signal.value)
        return actual_signal

    async def close(self) -> int | None:
        if self.status == JobStatus.RUNNING:
            # TODO force killing?
            self.signal(Signal.TERM)
            return await self.wait()
        await self.exit_reader.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
