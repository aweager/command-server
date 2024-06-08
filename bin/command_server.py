#!/usr/bin/env python3

import sys
import os
import queue
import threading

from lib.requests import *
from lib.operations import *
from lib.model import *
from lib.executor import *
from lib.socket_listener import *


def main(
    sock_addr: str, max_concurrency: int, load_stdio: Stdio, executor_command: list[str]
) -> int:
    if os.path.exists(sock_addr):
        try:
            os.unlink(sock_addr)
        except OSError:
            if os.path.exists(sock_addr):
                raise

    work_items: dict[int, WorkItem] = dict()
    ops_queue: queue.Queue[Operation] = queue.Queue()

    with token_io.mkfifo() as ops_fifo:
        socket_listener = SocketListener(
            sock_addr=sock_addr,
            ops_fifo_path=ops_fifo,
            ops_queue=ops_queue,
            work_items=work_items,
        )
        socket_listener_thread = threading.Thread(target=socket_listener.loop)
        socket_listener_thread.start()

        executor_manager = ExecutorManager(
            ops_fifo_path=ops_fifo,
            ops_queue=ops_queue,
            work_items=work_items,
            max_concurrency=max_concurrency,
            executor_command=executor_command,
        )
        executor_manager_thread = threading.Thread(
            target=executor_manager.loop, args=[load_stdio]
        )
        executor_manager_thread.start()

        while True:
            socket_listener_thread.join(1)
            executor_manager_thread.join(1)


if __name__ == "__main__":
    if len(sys.argv) < 8:
        raise ValueError(f"Received {len(sys.argv)} but require >= 8")

    sock_addr = sys.argv[1]
    max_concurrency = int(sys.argv[2])
    stdio = Stdio(
        stdin=sys.argv[3],
        stdout=sys.argv[4],
        stderr=sys.argv[5],
        status_pipe=sys.argv[6],
    )
    command = sys.argv[7:]

    if max_concurrency <= 0:
        max_concurrency = sys.maxsize

    sys.exit(main(sock_addr, max_concurrency, stdio, command))
