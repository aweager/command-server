from contextlib import contextmanager
import subprocess
import queue
import os
import logging
from typing import Generator, Optional

from .model import *
from .operations import *
from . import token_io
from .token_io import TokenReader, TokenWriter, Mode

_LOGGER = logging.getLogger(__name__)


class Executor:
    coproc_in: TokenWriter
    coproc_out: TokenReader

    def __init__(
        self,
        coproc_in: TokenWriter,
        coproc_out: TokenReader,
    ):
        self.coproc_in = coproc_in
        self.coproc_out = coproc_out

    def start_work_item(self, work_item: WorkItem) -> int:
        _LOGGER.warning(f"Starting work item: {work_item}")

        self.coproc_in.write(
            [
                str(work_item.id),
                work_item.dir,
                work_item.stdio.stdin,
                work_item.stdio.stdout,
                work_item.stdio.stderr,
                work_item.stdio.status_pipe,
                str(len(work_item.command)),
            ]
            + work_item.command
        )

        _LOGGER.warning("Reading pid")

        pid = int(self.coproc_out.read())
        return pid


@contextmanager
def make_executor(
    executor_command: list[str], stdio: Stdio, ops_fifo_path: str
) -> Generator[Executor, None, None]:
    with token_io.open_fds(
        (stdio.stdin, Mode.R), (stdio.stdout, Mode.W), (stdio.stderr, Mode.W)
    ) as stdio_fds:
        with token_io.mkfifo() as coproc_in_path, token_io.mkfifo() as coproc_out_path:
            with subprocess.Popen(
                args=executor_command
                + [coproc_in_path, coproc_out_path, ops_fifo_path],
                stdin=stdio_fds[0],
                stdout=stdio_fds[1],
                stderr=stdio_fds[2],
            ) as coproc:
                _LOGGER.warning(f"stdio: {stdio_fds}")
                try:
                    with token_io.open_pipe_writer(
                        coproc_in_path,
                    ) as coproc_in, token_io.open_pipe_reader(
                        coproc_out_path
                    ) as coproc_out:
                        _LOGGER.warning(f"in {coproc_in}, out {coproc_out}")
                        is_ready = coproc_out.read()
                        with token_io.open_pipe_writer(
                            stdio.status_pipe
                        ) as status_pipe:
                            if is_ready != "0":
                                try:
                                    code = int(is_ready)
                                except:
                                    code = 127
                                status_pipe.write([str(code)])
                                raise RuntimeError(
                                    f"Failed to start executor: {is_ready}"
                                )
                            else:
                                status_pipe.write(["0"])
                        yield Executor(coproc_in, coproc_out)
                finally:
                    coproc.terminate()


class ExecutorManager:
    work_items: dict[int, WorkItem]
    ops_queue: queue.Queue[Operation]
    ops_fifo_path: str
    max_concurrency: int
    executor_command: list[str]

    waiting_work_items: list[int]
    active_work_items: dict[int, int]

    def __init__(
        self,
        work_items: dict[int, WorkItem],
        ops_queue: queue.Queue[Operation],
        ops_fifo_path: str,
        max_concurrency: int,
        executor_command: list[str],
    ) -> None:
        self.work_items = work_items
        self.ops_queue = ops_queue
        self.ops_fifo_path = ops_fifo_path
        self.max_concurrency = max_concurrency
        self.executor_command = executor_command

        self.waiting_work_items = list()
        self.active_work_items = dict()
        _LOGGER.setLevel(logging.INFO)

    def loop(self, load_stdio: Stdio) -> None:
        _LOGGER.error(f"Ops fifo is {self.ops_fifo_path}")

        with token_io.open_pipe_reader(self.ops_fifo_path) as ops_fifo:
            while True:
                with make_executor(
                    self.executor_command, load_stdio, self.ops_fifo_path
                ) as executor:
                    while True:
                        _LOGGER.warning("Reading from ops fifo")
                        op_line = ops_fifo.read()
                        _LOGGER.warning(f"Got an op line: {op_line}")
                        operation = self.parse_op(op_line)
                        if operation:
                            _LOGGER.error(f"Got operation {operation}")
                            match operation:
                                case AddWorkItem(id):
                                    self.add_work_item(id)
                                case CompleteWorkItem(id):
                                    self.complete_work_item(id)
                                case SignalWorkItem(id, signal):
                                    self.signal_work_item(id, signal)
                                case ReloadExecutor():
                                    load_stdio = operation.stdio
                                    break
                        else:
                            _LOGGER.error(f"Received invalid operation")

                        self.maybe_start_work_item(executor)

    def add_work_item(self, id: int) -> None:
        if id in self.work_items:
            with token_io.open_pipe_writer(
                self.work_items[id].stdio.status_pipe
            ) as status_pipe:
                status_pipe.write([str(id)])

        self.waiting_work_items.append(id)

    def complete_work_item(self, id: int) -> None:
        if id in self.active_work_items:
            del self.active_work_items[id]

    def maybe_start_work_item(self, executor: Executor) -> None:
        if len(self.active_work_items) >= self.max_concurrency:
            return

        id: Optional[int] = None
        while len(self.waiting_work_items) > 0:
            id = self.waiting_work_items.pop(0)
            if id in self.work_items:
                break

        if not id:
            return

        pid = executor.start_work_item(self.work_items[id])
        if pid != -1:
            self.active_work_items[id] = pid
        _LOGGER.warning(f"Work item {id} -> {pid}")

    def signal_work_item(self, id: int, signal: SupportedSignal) -> None:
        if id in self.active_work_items:
            pid = self.active_work_items[id]
            _LOGGER.warning(f"Signaling job {id}, pid {pid} with {signal.value}")
            os.kill(pid, signal.value)
        elif id in self.work_items:
            work_item = self.work_items[id]
            with token_io.open_pipe_writer(work_item.stdio.status_pipe) as status_pipe:
                status_pipe.write([str(signal.value + 128)])
            del self.work_items[id]

    def parse_op(self, op_line: str) -> None | Operation:
        if op_line == "poll":
            return self.ops_queue.get()

        if not op_line.startswith("done "):
            return None

        id: int
        try:
            id = int(op_line[5:])
        except:
            return None

        return CompleteWorkItem(id)
