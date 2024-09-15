#!/usr/bin/env python3

import asyncio
import logging
import os
import pathlib
import signal
import sys
from asyncio import FIRST_COMPLETED, Event, Future
from functools import partial

import jrpc

from . import server_config
from .impl import JobApiImpl
from .server_config import CommandServerConfig

_LOGGER = logging.getLogger(__name__)


async def run_command_server(config: CommandServerConfig, term_future: Future[int]) -> int:
    logging.basicConfig(level=config.log_level, filename=config.log_file)

    _LOGGER.error(f"=== Starting server instance {os.getpid()} ===")

    stop_event = Event()

    impl = JobApiImpl(config, stop_event)
    connection_callback = jrpc.connection.client_connected_callback(impl.method_set())

    server = await asyncio.start_unix_server(connection_callback, path=config.socket_path)
    try:
        # async with impl:
        _LOGGER.info(f"Server listening on {config.socket_path}")
        try:
            await asyncio.wait(
                [asyncio.create_task(stop_event.wait()), term_future],
                return_when=FIRST_COMPLETED,
            )
        finally:
            _LOGGER.info("Server shutting down")
            server.close()

        if term_future.done():
            return term_future.result()
        return 0
    finally:
        try:
            os.unlink(config.socket_path)
        except Exception:
            # swallow
            pass


_TERMINATING_SIGNALS = [
    signal.SIGTERM,
    signal.SIGINT,
    signal.SIGQUIT,
    signal.SIGHUP,
]


def _handle_terminating_signals(
    signal: int,
    future: asyncio.Future[int],
):
    _LOGGER.info(f"Received {signal}, closing the server")
    future.set_result(signal)


async def main(config: CommandServerConfig) -> int:
    term_future: asyncio.Future[int] = asyncio.Future()
    for term_signal in _TERMINATING_SIGNALS:
        asyncio.get_running_loop().add_signal_handler(
            term_signal,
            partial(
                _handle_terminating_signals,
                signal=term_signal,
                future=term_future,
            ),
        )

    return await run_command_server(config, term_future)


if __name__ == "__main__":
    config = server_config.parse_config(sys.argv)
    os.environ["COMMAND_SERVER_LIB"] = str(pathlib.Path(__file__).parent.joinpath("lib"))
    sys.exit(asyncio.run(main(config)))
