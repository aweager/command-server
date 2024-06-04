import subprocess
import queue
import os
import logging
from typing import Optional

from .model import *
from .operations import *
from . import token_io
from .token_io import TokenReader, TokenWriter

_LOGGER = logging.getLogger(__name__)


class Executor:
    coproc: subprocess.Popen
    coproc_in_path: str
    coproc_out_path: str
    coproc_in: TokenWriter
    coproc_out: TokenReader

    def __init__(
        self,
        ops_fifo_path: str,
        executor_command: list[str],
        reload_args: ReloadExecutor,
    ):
        # TODO tmp file names
        # TODO reload args
        self.coproc_in_path = "./coproc_in"
        self.coproc_out_path = "./coproc_out"
        self.coproc = subprocess.Popen(args=executor_command)

        self.coproc_in = token_io.open_pipe_writer(self.coproc_in_path)
        self.coproc_out = token_io.open_pipe_reader(self.coproc_out_path)

        self.coproc_in.write([ops_fifo_path])

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.coproc.terminate()
        self.coproc_in.close()
        self.coproc_out.close()

    def start_work_item(self, work_item: WorkItem) -> int:
        _LOGGER.warning(f"Starting work item: {work_item}")

        self.coproc_in.write(
            [
                str(work_item.id),
                work_item.dir,
                work_item.stdin,
                work_item.stdout,
                work_item.stderr,
                work_item.response_pipe,
                str(len(work_item.command)),
            ]
            + work_item.command
        )

        _LOGGER.warning("Reading pid")

        pid = int(self.coproc_out.read())
        return pid


class ExecutorManager:
    work_items: dict[int, WorkItem]
    ops_queue: queue.Queue[Operation]
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

    def loop(self, initial_reload: ReloadExecutor) -> None:
        _LOGGER.error(f"Ops fifo is {self.ops_fifo_path}")

        reload_args = initial_reload

        while True:
            with Executor(
                self.ops_fifo_path, self.executor_command, reload_args
            ) as executor, token_io.open_pipe_reader(self.ops_fifo_path) as ops_fifo:
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
                                reload_args = operation
                                break
                    else:
                        _LOGGER.error(f"Received invalid operation")

                    self.maybe_start_work_item(executor)

    def add_work_item(self, id: int) -> None:
        work_item = self.work_items[id]
        if work_item:
            with token_io.open_pipe_writer(work_item.response_pipe) as response_pipe:
                response_pipe.write([str(id)])

        self.waiting_work_items.append(id)

    def complete_work_item(self, id: int) -> None:
        del self.active_work_items[id]

    def maybe_start_work_item(self, executor: Executor) -> None:
        if len(self.active_work_items) >= self.max_concurrency:
            return

        id: Optional[int] = None
        while len(self.waiting_work_items) > 0:
            id = self.waiting_work_items.pop(0)
            if self.work_items[id]:
                break

        if not id:
            return

        self.active_work_items[id] = executor.start_work_item(self.work_items[id])

    def signal_work_item(self, id: int, signal: SupportedSignal) -> None:
        work_item = self.work_items[id]

        if work_item:
            _LOGGER.warning(f"Signaling job {id} with {signal}")
            pid = self.active_work_items[id]
            os.kill(pid, signal.value)
        else:
            with token_io.open_pipe_writer(work_item.response_pipe) as response_pipe:
                response_pipe.write([str(signal.value + 128)])

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
