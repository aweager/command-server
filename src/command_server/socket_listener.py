import socket
import queue
import logging
import threading

from .requests import *
from .operations import *
from .model import *
from .token_io import TokenReader
from . import token_io

_LOGGER = logging.getLogger(__name__)


class SocketListener:
    sock_addr: str
    ops_queue: queue.SimpleQueue[Operation]
    terminate_event: threading.Event

    last_request_id: int

    def __init__(
        self,
        sock_addr: str,
        ops_queue: queue.SimpleQueue[Operation],
        terminate_event: threading.Event,
    ) -> None:
        self.sock_addr = sock_addr
        self.ops_queue = ops_queue
        self.terminate_event = terminate_event

        self.last_request_id = 0

    def loop(self) -> None:
        _LOGGER.info("Listening to socket")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(self.sock_addr)
            server.listen(1)
            while True:
                if self.terminate_event.is_set():
                    self.ops_queue.put(TerminateServer())
                    break

                request = self.read_next_request(server)
                match request:
                    case CallRequest():
                        _LOGGER.debug(f"Recevied call request: {request}")
                        self.last_request_id += 1
                        self.ops_queue.put(
                            AddWorkItem(
                                WorkItem(
                                    id=self.last_request_id,
                                    dir=request.dir,
                                    stdio=request.stdio,
                                    command=request.command,
                                )
                            )
                        )
                    case SignalRequest():
                        _LOGGER.debug(f"Recevied signal request: {request}")
                        self.ops_queue.put(SignalWorkItem(request.id, request.signal))
                    case StatusRequest():
                        _LOGGER.debug(f"Received status request: {request}")
                        self.ops_queue.put(DisplayStatus(request.stdio))
                    case ReloadRequest():
                        _LOGGER.debug(f"Recevied reload request: {request}")
                        self.ops_queue.put(ReloadExecutor(request.args))
                    case TerminateRequest():
                        _LOGGER.debug(f"Received terminate request: {request}")
                        self.terminate_event.set()
                    case _:
                        pass
        _LOGGER.info("Socket listener shutting down")

    def read_next_request(self, server: socket.socket) -> None | Request:
        with token_io.accept_connection(server) as reader:
            _LOGGER.debug("Received connection")
            verb = reader.read()
            match verb:
                case "call":
                    return self.read_call_request(reader)
                case "sig":
                    return self.read_sig_request(reader)
                case "status":
                    return self.read_status_request(reader)
                case "reload":
                    return self.read_reload_request(reader)
                case "term":
                    return self.read_terminate_request(reader)
                case _:
                    return None

    def read_call_request(self, reader: TokenReader) -> None | CallRequest:
        _LOGGER.debug("Reading call")
        body = reader.read_multiple(6)
        if len(body) != 6:
            _LOGGER.info(f"Call: invalid request with {len(body)} lines: {body}")
            return None

        dir, stdin, stdout, stderr, status_pipe, num_args_as_str = body

        num_args: int
        try:
            num_args = int(num_args_as_str)
        except:
            _LOGGER.info(f"Call: num args not an int: {num_args_as_str}")
            return None

        if num_args < 1:
            _LOGGER.info(f"Call: num args is < 1: {num_args}")
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
            _LOGGER.info(f"Sig: invalid request has {len(body)} lines: {body}")
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

    def read_status_request(self, reader: TokenReader) -> None | StatusRequest:
        body = reader.read_multiple(4)
        if len(body) != 4:
            _LOGGER.info(f"Status: invalid request has {len(body)} lines: {body}")
            return None

        return StatusRequest(
            Stdio(
                stdin=body[0],
                stdout=body[1],
                stderr=body[2],
                status_pipe=body[3],
            )
        )

    def read_reload_request(self, reader: TokenReader) -> None | ReloadRequest:
        body = reader.read_multiple(4)
        if len(body) != 4:
            _LOGGER.info(f"Reload: invalid request has {len(body)} lines: {body}")
            return None

        return ReloadRequest(
            Stdio(
                stdin=body[0],
                stdout=body[1],
                stderr=body[2],
                status_pipe=body[3],
            )
        )

    def read_terminate_request(self, _: TokenReader) -> None | TerminateRequest:
        return TerminateRequest()
