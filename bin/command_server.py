#!/usr/bin/env python3

import socket
import io
import sys
import tempfile
import os
import queue
import threading
import logging
import subprocess
from typing import Optional

from lib.requests import *
from lib.operations import *
from lib.model import *


class NullLineReader:
    connection: socket.socket

    lines: list[str]
    curr_line: str

    def __init__(self, connection: socket.socket) -> None:
        self.connection = connection
        self.lines = list()
        self.curr_line = ""

    def readlines(self, num: int) -> list[str]:
        result: list[str] = list()
        for _ in range(num):
            line = self.readline()
            if line:
                result.append(line)
            else:
                return result

        return result

    def readline(self) -> Optional[str]:
        if len(self.lines) > 0:
            return self.lines.pop(0)

        data = self.connection.recv(1024)
        if data:
            data_lines = data.decode().split("\0")
            result = self.curr_line + data_lines[0]
            self.curr_line = data_lines[-1]
            self.lines = data_lines[1:-1]
            return result
        else:
            return None


class SocketListener:
    server: socket.socket
    ops_fifo: io.TextIOWrapper
    ops_queue: queue.Queue[Operation]
    work_items: dict[int, WorkItem]

    last_request_id: int
    logger: logging.Logger

    def __init__(
        self,
        server: socket.socket,
        ops_fifo: io.TextIOWrapper,
        ops_queue: queue.Queue[Operation],
        work_items: dict[int, WorkItem],
    ) -> None:
        self.server = server
        self.ops_fifo = ops_fifo
        self.ops_queue = ops_queue
        self.work_items = work_items

        self.last_request_id = 0
        self.logger = logging.getLogger("SocketListener")
        self.logger.setLevel(logging.INFO)

    def loop(self) -> None:
        self.server.listen(1)
        while True:
            request = self.read_next_request()
            match request:
                case CallRequest():
                    self.logger.error(f"Recevied call request: {request}")
                    self.last_request_id += 1
                    self.work_items[self.last_request_id] = WorkItem(
                        id=self.last_request_id,
                        dir=request.dir,
                        stdin=request.stdin,
                        stdout=request.stdout,
                        stderr=request.stderr,
                        response_pipe=request.response_pipe,
                        command=request.command,
                    )
                    self.ops_queue.put(AddWorkItem(self.last_request_id))
                    self.poll_fifo()
                case SignalRequest():
                    self.logger.error(f"Recevied signal request: {request}")
                    self.ops_queue.put(SignalWorkItem(request.id, request.signal))
                    self.poll_fifo()
                case ReloadRequest():
                    self.logger.error(f"Recevied reload request: {request}")
                    self.ops_queue.put(
                        ReloadExecutor(
                            dir=request.dir,
                            stdin=request.stdin,
                            stdout=request.stdout,
                            stderr=request.stderr,
                            response_pipe=request.response_pipe,
                        )
                    )
                    self.poll_fifo()

    def poll_fifo(self) -> None:
        self.ops_fifo.write("poll\n")
        self.ops_fifo.flush()
        self.logger.warning("Polled ops fifo")

    def read_next_request(self) -> Request:
        connection, _ = self.server.accept()
        try:
            self.logger.warning("Received connection")
            reader = NullLineReader(connection)
            verb = reader.readline()
            match verb:
                case "call":
                    return self.read_call_request(reader)
                case "sig":
                    return self.read_sig_request(reader)
                case "reload":
                    return self.read_reload_request(reader)
                case _:
                    return None
        finally:
            connection.close()

    def read_call_request(self, reader: NullLineReader) -> None | CallRequest:
        self.logger.warning("Reading call")
        body = reader.readlines(6)
        if len(body) != 6:
            self.logger.error(f"Call has {len(body)} lines: {body}")
            return None
        return CallRequest(
            dir=body[0],
            stdin=body[1],
            stdout=body[2],
            stderr=body[3],
            response_pipe=body[4],
            command=body[5],
        )

    def read_sig_request(self, reader: NullLineReader) -> None | SignalRequest:
        body = reader.readlines(2)
        if len(body) != 2:
            self.logger.error(f"Signal has {len(body)} lines")
            return None

        id: int = 0
        try:
            id = int(body[0])
        except:
            return None

        if id > self.last_request_id or id < 0:
            return None

        signal: SupportedSignal
        try:
            signal = SupportedSignal[body[1]]
        except:
            return None

        return SignalRequest(id=id, signal=signal)

    def read_reload_request(self, reader: NullLineReader) -> None | ReloadRequest:
        body = reader.readlines(5)
        if len(body) != 5:
            self.logger.error(f"Reload has {len(body)} lines")
            return None

        return ReloadRequest(
            dir=body[0],
            stdin=body[1],
            stdout=body[2],
            stderr=body[3],
            response_pipe=body[4],
        )


class Executor:
    coproc: subprocess.Popen

    def __init__(
        self,
        ops_fifo_path: str,
        coproc: subprocess.Popen,
    ):
        self.coproc = coproc
        self.write_to_coproc([ops_fifo_path])

    def write_to_coproc(self, data: list[str]) -> None:
        serialized_data = "\0".join(data)
        serialized_data += "\0"
        coproc_stdin = self.coproc.stdin
        assert coproc_stdin
        coproc_stdin.write(serialized_data)
        coproc_stdin.flush()

    def start_work_item(self, work_item: WorkItem) -> int:
        with open(work_item.response_pipe, "w") as response_pipe:
            response_pipe.write(f"{id}\n")

        self.write_to_coproc(
            [
                str(work_item.id),
                work_item.dir,
                work_item.stdin,
                work_item.stdout,
                work_item.stderr,
                work_item.response_pipe,
                work_item.command,
            ]
        )

        coproc_stdout = self.coproc.stdout
        assert coproc_stdout
        pid = int(coproc_stdout.readline().strip())
        return pid


class ExecutorManager:
    work_items: dict[int, WorkItem]
    ops_queue: queue.Queue[Operation]
    max_concurrency: int
    executor_command: list[str]

    ops_fifo: io.TextIOWrapper
    waiting_work_items: list[int]
    active_work_items: dict[int, int]
    logger: logging.Logger

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

        self.ops_fifo = open(ops_fifo_path, "r")
        self.waiting_work_items = list()
        self.active_work_items = dict()
        self.logger = logging.getLogger("ExecutorManager")
        self.logger.setLevel(logging.INFO)

    def loop(self, initial_reload: ReloadExecutor) -> None:
        self.logger.error(f"Ops fifo is {self.ops_fifo_path}")

        reload_args = initial_reload

        while True:
            with subprocess.Popen(
                args=self.executor_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                bufsize=1,
            ) as coproc:
                executor = Executor(self.ops_fifo_path, coproc)
                while True:
                    self.logger.warning("Reading from ops fifo")
                    op_line = self.ops_fifo.readline().strip()
                    self.logger.warning(f"Got an op line: {op_line}")
                    operation = self.parse_op(op_line)
                    if operation:
                        self.logger.error(f"Got operation {operation}")
                        match operation:
                            case AddWorkItem(id):
                                self.waiting_work_items.append(id)
                            case CompleteWorkItem(id):
                                if self.active_work_items[id]:
                                    del self.active_work_items[id]
                            case ReloadExecutor():
                                reload_args = operation
                                break
                            case SignalWorkItem(id, signal):
                                if self.active_work_items[id]:
                                    self.signal_active_work_item(id, signal)
                                elif self.work_items[id]:
                                    self.signal_inactive_work_item(id, signal)
                    else:
                        self.logger.error(f"Received invalid operation")

                    self.maybe_start_work_item(executor)

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

    def signal_active_work_item(self, id: int, signal: SupportedSignal):
        self.logger.warning(f"Signaling job {id} with {signal}")
        pid = self.active_work_items[id]
        os.kill(pid, signal.value)

    def signal_inactive_work_item(self, id: int, signal: SupportedSignal):
        if not self.work_items[id]:
            return

        work_item = self.work_items[id]
        with open(work_item.response_pipe, "w") as response_pipe:
            response_pipe.write(f"{signal.value + 128}\n")
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


def main(sock_addr: str, max_concurrency: int, executor_command: list[str]) -> int:
    if os.path.exists(sock_addr):
        try:
            os.unlink(sock_addr)
        except OSError:
            if os.path.exists(sock_addr):
                raise

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_addr)

    ops_fifo_path = os.path.join(tempfile.mkdtemp(), "ops")
    os.mkfifo(ops_fifo_path)

    work_items: dict[int, WorkItem] = dict()
    ops_queue: queue.Queue[Operation] = queue.Queue()

    socket_listener = SocketListener(
        server=server,
        ops_queue=ops_queue,
        work_items=work_items,
        ops_fifo=open(ops_fifo_path, "w"),
    )
    socket_listener_thread = threading.Thread(target=socket_listener.loop)
    socket_listener_thread.start()

    executor_manager = ExecutorManager(
        ops_fifo_path=ops_fifo_path,
        ops_queue=ops_queue,
        work_items=work_items,
        max_concurrency=max_concurrency,
        executor_command=executor_command,
    )
    executor_manager_thread = threading.Thread(target=executor_manager.loop)
    executor_manager_thread.start()

    while True:
        socket_listener_thread.join(1)
        executor_manager_thread.join(1)


if __name__ == "__main__":
    sys.exit(main("./socket", 1, ["./print-args.zsh"]))
