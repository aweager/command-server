#!/usr/bin/env python3

import pathlib
import sys

sys.path = [str(pathlib.Path(__file__).parent)] + sys.path

import sys
import os
import queue
import threading

from command_server import server_config
from command_server.server_config import CommandServerConfig
from command_server.requests import *
from command_server.operations import *
from command_server.model import *
from command_server.executor import *
from command_server.socket_listener import *

_LOGGER = logging.getLogger(__name__)


def main(config: CommandServerConfig) -> int:
    logging.basicConfig(level=config.log_level, filename=config.log_file)

    _LOGGER.error(f"=== Starting server instance {os.getpid()} ===")

    try:
        if os.path.exists(config.socket_address):
            try:
                os.unlink(config.socket_address)
            except OSError:
                if os.path.exists(config.socket_address):
                    raise
        elif not os.path.exists(pathlib.Path(config.socket_address).parent):
            raise RuntimeError("Directory does not exist")
    except Exception as ex:
        _LOGGER.error(
            f"Could not bind to socket {config.socket_address}", exc_info=True
        )
        with open(
            config.initial_load_stdio.stderr, "w"
        ) as stderr, token_io.open_pipe_writer(
            config.initial_load_stdio.status_pipe
        ) as status_pipe:
            stderr.write(f"Could not bind to socket {config.socket_address}: {ex}\n")
            status_pipe.write(["128"])
            return 128

    ops_queue: queue.SimpleQueue[Operation] = queue.SimpleQueue()

    terminate_event = threading.Event()

    socket_listener = SocketListener(
        sock_addr=config.socket_address,
        ops_queue=ops_queue,
        terminate_event=terminate_event,
    )
    socket_listener_thread = threading.Thread(target=socket_listener.loop)
    socket_listener_thread.start()

    executor_manager = ExecutorManager(
        ops_queue=ops_queue,
        config=config.executor_config,
        terminate_event=terminate_event,
    )
    executor_manager_thread = threading.Thread(
        target=executor_manager.loop, args=[config.initial_load_stdio]
    )
    executor_manager_thread.start()

    while socket_listener_thread.is_alive() and executor_manager_thread.is_alive():
        socket_listener_thread.join(1)
        executor_manager_thread.join(1)

    os.unlink(config.socket_address)
    return 0


if __name__ == "__main__":
    config = server_config.parse_config(sys.argv)
    sys.exit(main(config))
