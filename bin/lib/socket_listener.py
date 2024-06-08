import socket
import queue
import logging

from .requests import *
from .operations import *
from .model import *
from .token_io import TokenWriter, TokenReader
from . import token_io


class SocketListener:
    sock_addr: str
    ops_fifo_path: str
    ops_queue: queue.Queue[Operation]
    work_items: dict[int, WorkItem]

    last_request_id: int
    logger: logging.Logger

    def __init__(
        self,
        sock_addr: str,
        ops_fifo_path: str,
        ops_queue: queue.Queue[Operation],
        work_items: dict[int, WorkItem],
    ) -> None:
        self.sock_addr = sock_addr
        self.ops_fifo_path = ops_fifo_path
        self.ops_queue = ops_queue
        self.work_items = work_items

        self.last_request_id = 0
        self.logger = logging.getLogger("SocketListener")
        self.logger.setLevel(logging.INFO)

    def loop(self) -> None:
        self.logger.warning("Listening to socket")
        with socket.socket(
            socket.AF_UNIX, socket.SOCK_STREAM
        ) as server, token_io.open_pipe_writer(self.ops_fifo_path) as ops_fifo:
            server.bind(self.sock_addr)
            server.listen(1)
            while True:
                request = self.read_next_request(server)
                match request:
                    case CallRequest():
                        self.logger.error(f"Recevied call request: {request}")
                        self.last_request_id += 1
                        self.work_items[self.last_request_id] = WorkItem(
                            id=self.last_request_id,
                            dir=request.dir,
                            stdio=request.stdio,
                            command=request.command,
                        )
                        self.ops_queue.put(AddWorkItem(self.last_request_id))
                        self.poll_fifo(ops_fifo)
                    case SignalRequest():
                        self.logger.error(f"Recevied signal request: {request}")
                        self.ops_queue.put(SignalWorkItem(request.id, request.signal))
                        self.poll_fifo(ops_fifo)
                    case ReloadRequest():
                        self.logger.error(f"Recevied reload request: {request}")
                        self.ops_queue.put(ReloadExecutor(request.args))
                        self.poll_fifo(ops_fifo)
                    case _:
                        pass

    def poll_fifo(self, ops_fifo: TokenWriter) -> None:
        ops_fifo.write(["poll"])
        self.logger.warning("Polled ops fifo")

    def read_next_request(self, server: socket.socket) -> None | Request:
        with token_io.accept_connection(server) as reader:
            self.logger.warning("Received connection")
            verb = reader.read()
            match verb:
                case "call":
                    return self.read_call_request(reader)
                case "sig":
                    return self.read_sig_request(reader)
                case "reload":
                    return self.read_reload_request(reader)
                case _:
                    return None

    def read_call_request(self, reader: TokenReader) -> None | CallRequest:
        self.logger.warning("Reading call")
        body = reader.read_multiple(6)
        if len(body) != 6:
            self.logger.error(f"Call has {len(body)} lines: {body}")
            return None

        dir, stdin, stdout, stderr, status_pipe, num_args_as_str = body

        num_args: int
        try:
            num_args = int(num_args_as_str)
        except:
            self.logger.error(f"Num args not an int: {num_args_as_str}")
            return None

        if num_args < 1:
            self.logger.error(f"Num args is < 1: {num_args}")
            return None

        command = reader.read_multiple(num_args)

        return CallRequest(
            dir,
            Stdio(
                stdin,
                stdout,
                stderr,
                status_pipe,
            ),
            command,
        )

    def read_sig_request(self, reader: TokenReader) -> None | SignalRequest:
        body = reader.read_multiple(2)
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

    def read_reload_request(self, reader: TokenReader) -> None | ReloadRequest:
        body = reader.read_multiple(4)
        if len(body) != 4:
            self.logger.error(f"Reload has {len(body)} lines")
            return None

        return ReloadRequest(
            Stdio(
                stdin=body[0],
                stdout=body[1],
                stderr=body[2],
                status_pipe=body[3],
            )
        )
