from contextlib import contextmanager
import io
import pathlib
import subprocess
import queue
import os
import logging
import sys
import threading
from typing import Generator, Optional

from .server_config import CommandServerConfig, ExecutorConfig
from .model import *
from .operations import *
from . import token_io
from .token_io import TokenReader, TokenWriter, Mode
from . import server_config

_LOGGER = logging.getLogger(__name__)

os.environ["COMMAND_SERVER_LIB"] = str(
    pathlib.Path(__file__).parent.parent.parent.joinpath("lib")
)


@dataclass
class CompletionMonitor:
    work_item_id: int
    completion_fifo: io.TextIOWrapper
    ops_queue: queue.SimpleQueue[Operation]

    def block_until_done(self) -> None:
        with self.completion_fifo:
            self.completion_fifo.readline()
            self.ops_queue.put(CompleteWorkItem(self.work_item_id))


@dataclass
class Executor:
    coproc_in: TokenWriter
    coproc_out: TokenReader
    ops_queue: queue.SimpleQueue[Operation]

    def start_work_item(self, work_item: WorkItem) -> int:
        _LOGGER.debug(f"Starting work item: {work_item}")

        with token_io.mkfifo("completion") as completion_fifo:
            self.coproc_in.write(
                [
                    str(work_item.id),
                    work_item.dir,
                    work_item.stdio.stdin,
                    work_item.stdio.stdout,
                    work_item.stdio.stderr,
                    work_item.stdio.status_pipe,
                    completion_fifo,
                    str(len(work_item.command)),
                ]
                + work_item.command
            )

            _LOGGER.debug("Starting completion listener")
            threading.Thread(
                target=CompletionMonitor(
                    work_item.id, open(completion_fifo), self.ops_queue
                ).block_until_done
            ).start()

            _LOGGER.debug("Reading pid")
            pid = int(self.coproc_out.read())
            return pid


@contextmanager
def make_executor(
    working_dir: str,
    executor_command: str,
    executor_args: list[str],
    stdio: Stdio,
    ops_queue: queue.SimpleQueue[Operation],
) -> Generator[Executor, None, None]:
    with (
        token_io.open_fds(
            (stdio.stdin, Mode.R), (stdio.stdout, Mode.W), (stdio.stderr, Mode.W)
        ) as stdio_fds,
        token_io.mkfifo("coproc-in") as coproc_in_path,
        token_io.mkfifo("coproc-out") as coproc_out_path,
        subprocess.Popen(
            cwd=working_dir,
            args=[executor_command, coproc_in_path, coproc_out_path] + executor_args,
            stdin=stdio_fds[0],
            stdout=stdio_fds[1],
            stderr=stdio_fds[2],
        ) as coproc,
        token_io.open_pipe_writer(coproc_in_path) as coproc_in,
        token_io.open_pipe_reader(coproc_out_path) as coproc_out,
    ):
        try:
            _LOGGER.debug(
                f"Started coprocess: '{executor_command}' with additional args {executor_args}"
            )
            is_ready = coproc_out.read()
            with token_io.open_pipe_writer(stdio.status_pipe) as status_pipe:
                if is_ready != "0":
                    try:
                        code = int(is_ready)
                    except:
                        code = 127
                    status_pipe.write([str(code)])
                    raise RuntimeError(f"Failed to start executor: {is_ready}")
                else:
                    status_pipe.write(["0"])
            yield Executor(coproc_in, coproc_out, ops_queue)
        finally:
            coproc.terminate()


class ExecutorManager:
    ops_queue: queue.SimpleQueue[Operation]
    config: ExecutorConfig
    terminate_event: threading.Event

    pending_work_items: dict[int, WorkItem]
    active_work_items: dict[int, WorkItem]
    active_pids: dict[int, int]

    def __init__(
        self,
        ops_queue: queue.SimpleQueue[Operation],
        config: ExecutorConfig,
        terminate_event: threading.Event,
    ) -> None:
        self.ops_queue = ops_queue
        self.config = config
        self.terminate_event = terminate_event
        self.pending_work_items = dict()
        self.active_work_items = dict()
        self.active_pids = dict()

    def loop(self, load_stdio: Stdio) -> None:
        while True:
            if self.terminate_event.is_set():
                self.interrupt_pending_work_items()
                break

            with make_executor(
                self.config.working_dir,
                self.config.command,
                self.config.args,
                load_stdio,
                self.ops_queue,
            ) as executor:
                while True:
                    operation = self.ops_queue.get()
                    _LOGGER.debug(f"Got operation {operation}")
                    match operation:
                        case AddWorkItem(work_item):
                            self.add_work_item(work_item)
                        case CompleteWorkItem(id):
                            self.complete_work_item(id)
                        case SignalWorkItem(id, signal):
                            self.signal_work_item(id, signal)
                        case DisplayStatus(stdio):
                            self.display_status(stdio)
                        case ReloadExecutor():
                            new_config = self.reload_config(operation.stdio)
                            if new_config:
                                self.config = new_config
                                load_stdio = operation.stdio
                                break
                        case TerminateServer():
                            break

                    self.maybe_start_work_item(executor)

        _LOGGER.info("Executor shutting down")

    def add_work_item(self, work_item: WorkItem) -> None:
        with token_io.open_pipe_writer(work_item.stdio.status_pipe) as status_pipe:
            status_pipe.write([str(work_item.id)])

        self.pending_work_items[work_item.id] = work_item

    def complete_work_item(self, id: int) -> None:
        if id in self.active_pids:
            del self.active_pids[id]
            del self.active_work_items[id]

    def maybe_start_work_item(self, executor: Executor) -> None:
        if len(self.active_pids) >= self.config.max_concurrency:
            return

        if len(self.pending_work_items) == 0:
            return

        id, work_item = self.pending_work_items.popitem()

        pid = executor.start_work_item(work_item)
        if pid != -1:
            self.active_pids[id] = pid
            self.active_work_items[id] = work_item
        _LOGGER.debug(f"Work item {id} -> {pid}")

    def signal_work_item(self, id: int, signal: SupportedSignal) -> None:
        if signal in self.config.signal_translations.mapping:
            signal = self.config.signal_translations.mapping[signal]

        if id in self.active_pids:
            pid = self.active_pids[id]
            _LOGGER.debug(f"Signaling job {id}, pid {pid} with {signal}")
            try:
                os.kill(pid, signal.value)
            except Exception as e:
                # Swallow and log
                _LOGGER.info(f"Error killing pid {pid}: {e}")
                pass
        elif id in self.pending_work_items:
            _LOGGER.debug(f"Simulating signal {signal} for job {id}")
            work_item = self.pending_work_items[id]
            with token_io.open_pipe_writer(work_item.stdio.status_pipe) as status_pipe:
                status_pipe.write([str(signal.value + 128)])
        else:
            _LOGGER.debug(f"Job {id} was already completed")

    def display_status(self, stdio: Stdio) -> None:
        with (
            open(stdio.stdout, "w") as stdout,
            token_io.open_pipe_writer(stdio.status_pipe) as status_pipe,
        ):
            stdout.write("Pending jobs:\n")
            for id, work_item in self.pending_work_items.items():
                stdout.write(f"    {id} -> {work_item.command}\n")

            stdout.write("Active jobs:\n")
            for id, pid in self.active_pids.items():
                work_item = self.active_work_items[id]
                stdout.write(f"    {id} -> {pid} {work_item.command}\n")
            stdout.flush()
            status_pipe.write([str(0)])

    def reload_config(self, reload_stdio: Stdio) -> Optional[ExecutorConfig]:
        all_config: CommandServerConfig
        try:
            all_config = server_config.parse_config(sys.argv)
        except Exception as ex:
            with (
                token_io.open_pipe_writer(reload_stdio.stderr) as stderr,
                token_io.open_pipe_writer(reload_stdio.status_pipe) as status_pipe,
            ):
                stderr.write([f"Failed to parse config on reload: {ex}"])
                status_pipe.write(["127"])
                return None

        logging.basicConfig(
            level=all_config.log_level, filename=all_config.log_file, force=True
        )
        return all_config.executor_config

    def interrupt_pending_work_items(self) -> None:
        _LOGGER.info("Cancelling pending work items")
        for work_item in self.pending_work_items.values():
            _LOGGER.debug(f"Interrupting work item: {work_item}")
            with token_io.open_pipe_writer(work_item.stdio.status_pipe) as status_pipe:
                status_pipe.write([str(128 + SupportedSignal.INT.value)])
