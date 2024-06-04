#!/usr/bin/env python3

import socket
import sys
import tempfile
import os
import queue
import threading

from lib.requests import *
from lib.operations import *
from lib.model import *
from lib.executor import *
from lib.socket_listener import *


def main(sock_addr: str, max_concurrency: int, executor_command: list[str]) -> int:
    if os.path.exists(sock_addr):
        try:
            os.unlink(sock_addr)
        except OSError:
            if os.path.exists(sock_addr):
                raise

    ops_fifo_path = os.path.join(tempfile.mkdtemp(), "ops")
    os.mkfifo(ops_fifo_path)

    work_items: dict[int, WorkItem] = dict()
    ops_queue: queue.Queue[Operation] = queue.Queue()

    socket_listener = SocketListener(
        sock_addr=sock_addr,
        ops_fifo_path=ops_fifo_path,
        ops_queue=ops_queue,
        work_items=work_items,
    )
    socket_listener_thread = threading.Thread(target=socket_listener.loop)
    socket_listener_thread.start()

    initial_reload = ReloadExecutor(
        dir="",
        stdin="",
        stdout="",
        stderr="",
        response_pipe="",
    )

    executor_manager = ExecutorManager(
        ops_fifo_path=ops_fifo_path,
        ops_queue=ops_queue,
        work_items=work_items,
        max_concurrency=max_concurrency,
        executor_command=executor_command,
    )
    executor_manager_thread = threading.Thread(
        target=executor_manager.loop, args=[initial_reload]
    )
    executor_manager_thread.start()

    while True:
        socket_listener_thread.join(1)
        executor_manager_thread.join(1)


if __name__ == "__main__":
    sys.exit(main("./socket", 1, ["./lib/print-args.sh"]))
