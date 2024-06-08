#!/usr/bin/env python3

import sys
import os
import queue
import threading

from lib import server_config
from lib.server_config import CommandServerConfig
from lib.requests import *
from lib.operations import *
from lib.model import *
from lib.executor import *
from lib.socket_listener import *

_LOGGER = logging.getLogger(__name__)


def main(config: CommandServerConfig) -> int:
    logging.basicConfig(level=config.log_level)

    _LOGGER.error(f"=== Starting server instance {os.getpid()} ===")

    if os.path.exists(config.socket_address):
        try:
            os.unlink(config.socket_address)
        except OSError:
            if os.path.exists(config.socket_address):
                raise

    work_items: dict[int, WorkItem] = dict()
    ops_queue: queue.Queue[Operation] = queue.Queue()

    terminate_event = threading.Event()

    with token_io.mkfifo() as ops_fifo:
        socket_listener = SocketListener(
            sock_addr=config.socket_address,
            ops_fifo_path=ops_fifo,
            ops_queue=ops_queue,
            work_items=work_items,
            terminate_event=terminate_event,
        )
        socket_listener_thread = threading.Thread(target=socket_listener.loop)
        socket_listener_thread.start()

        executor_manager = ExecutorManager(
            ops_fifo_path=ops_fifo,
            ops_queue=ops_queue,
            work_items=work_items,
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

    return 0


if __name__ == "__main__":
    config = server_config.parse_config(sys.argv[1:])
    sys.exit(main(config))
