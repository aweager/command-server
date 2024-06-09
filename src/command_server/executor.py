from contextlib import contextmanager
import pathlib
import subprocess
import queue
import os
import logging
import sys
import threading
from typing import Generator, Optional

from .server_config import ExecutorConfig
from .model import *
from .operations import *
from . import token_io
from .token_io import TokenReader, TokenWriter, Mode
from . import server_config

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
        _LOGGER.debug(f"Starting work item: {work_item}")

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

        _LOGGER.debug("Reading pid")

        pid = int(self.coproc_out.read())
        return pid


@contextmanager
def make_executor(
    working_dir: str, executor_command: list[str], stdio: Stdio, ops_fifo_path: str
) -> Generator[Executor, None, None]:
    with token_io.open_fds(
        (stdio.stdin, Mode.R), (stdio.stdout, Mode.W), (stdio.stderr, Mode.W)
    ) as stdio_fds:
        with token_io.mkfifo() as coproc_in_path, token_io.mkfifo() as coproc_out_path:
            os.environ["COMMAND_SERVER_LIB"] = str(
                pathlib.Path(__file__).parent.parent.parent.joinpath("lib")
            )
            with subprocess.Popen(
                cwd=working_dir,
                args=executor_command
                + [coproc_in_path, coproc_out_path, ops_fifo_path],
                stdin=stdio_fds[0],
                stdout=stdio_fds[1],
                stderr=stdio_fds[2],
            ) as coproc:
                _LOGGER.debug(f"stdio: {stdio_fds}")
                try:
                    with token_io.open_pipe_writer(
                        coproc_in_path,
                    ) as coproc_in, token_io.open_pipe_reader(
                        coproc_out_path
                    ) as coproc_out:
                        _LOGGER.debug(f"in {coproc_in}, out {coproc_out}")
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
    config: ExecutorConfig
    terminate_event: threading.Event

    waiting_work_items: list[int]
    active_work_items: dict[int, int]

    def __init__(
        self,
        work_items: dict[int, WorkItem],
        ops_queue: queue.Queue[Operation],
        ops_fifo_path: str,
        config: ExecutorConfig,
        terminate_event: threading.Event,
    ) -> None:
        self.work_items = work_items
        self.ops_queue = ops_queue
        self.ops_fifo_path = ops_fifo_path
        self.config = config
        self.terminate_event = terminate_event

        self.waiting_work_items = list()
        self.active_work_items = dict()

    def loop(self, load_stdio: Stdio) -> None:
        _LOGGER.debug(f"Ops fifo is {self.ops_fifo_path}")

        with token_io.open_pipe_reader(self.ops_fifo_path) as ops_fifo:
            while True:
                if self.terminate_event.is_set():
                    self.interrupt_waiting_work_items()
                    break

                with make_executor(
                    self.config.working_dir,
                    self.config.command,
                    load_stdio,
                    self.ops_fifo_path,
                ) as executor:
                    while True:
                        _LOGGER.debug("Reading from ops fifo")
                        op_line = ops_fifo.read()
                        _LOGGER.debug(f"Got an op line: {op_line}")
                        operation = self.parse_op(op_line)
                        if operation:
                            _LOGGER.debug(f"Got operation {operation}")
                            match operation:
                                case AddWorkItem(id):
                                    self.add_work_item(id)
                                case CompleteWorkItem(id):
                                    self.complete_work_item(id)
                                case SignalWorkItem(id, signal):
                                    self.signal_work_item(id, signal)
                                case ReloadExecutor():
                                    new_config = self.reload_config(operation.stdio)
                                    if new_config:
                                        self.config = new_config
                                        load_stdio = operation.stdio
                                        break
                                case TerminateServer():
                                    break
                        else:
                            _LOGGER.info(f"Received invalid operation: {op_line}")

                        self.maybe_start_work_item(executor)

        _LOGGER.info("Executor shutting down")

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
        if len(self.active_work_items) >= self.config.max_concurrency:
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
        _LOGGER.debug(f"Work item {id} -> {pid}")

    def signal_work_item(self, id: int, signal: SupportedSignal) -> None:
        if signal in self.config.signal_translations.mapping:
            signal = self.config.signal_translations.mapping[signal]
        if id in self.active_work_items:
            pid = self.active_work_items[id]
            _LOGGER.debug(f"Signaling job {id}, pid {pid} with {signal}")
            os.kill(pid, signal.value)
        elif id in self.work_items:
            work_item = self.work_items[id]
            with token_io.open_pipe_writer(work_item.stdio.status_pipe) as status_pipe:
                status_pipe.write([str(signal.value + 128)])
            del self.work_items[id]

    def reload_config(self, reload_stdio: Stdio) -> Optional[ExecutorConfig]:
        try:
            return server_config.parse_config(sys.argv).executor_config
        except Exception as ex:
            with token_io.open_pipe_writer(
                reload_stdio.stderr
            ) as stderr, token_io.open_pipe_writer(
                reload_stdio.status_pipe
            ) as status_pipe:
                stderr.write([f"Failed to parse config on reload: {ex}"])
                status_pipe.write(["127"])
                return None

    def interrupt_waiting_work_items(self) -> None:
        _LOGGER.info("Cancelling pending work items")
        for id in self.waiting_work_items:
            if id in self.work_items:
                work_item = self.work_items[id]
                _LOGGER.debug(f"Interrupting work item: {work_item}")
                with token_io.open_pipe_writer(
                    self.work_items[id].stdio.status_pipe
                ) as status_pipe:
                    status_pipe.write([str(128 + SupportedSignal.INT.value)])

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