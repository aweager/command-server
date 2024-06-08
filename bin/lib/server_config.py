from configparser import ConfigParser
from argparse import ArgumentParser
from dataclasses import dataclass
from typing import Optional
import pathlib
import shlex
import sys

from .model import SupportedSignal, Stdio


@dataclass
class SignalTranslations:
    mapping: dict[SupportedSignal, SupportedSignal]


@dataclass
class ExecutorConfig:
    command: list[str]
    max_concurrency: int
    signal_translations: SignalTranslations


@dataclass
class CommandServerConfig:
    socket_address: str
    initial_load_stdio: Stdio
    executor_config: ExecutorConfig


def parse_config(args: list[str]) -> CommandServerConfig:
    arg_parser = ArgumentParser(
        prog="command_server.py",
        description="Server to run commands in a different environment",
        epilog="See http://www.github.com/aweager/command-server for details",
    )

    arg_parser.add_argument(
        "--config-file",
        type=pathlib.Path,
        help="Configuration file to base the server on",
    )
    arg_parser.add_argument(
        "--max-concurrency", type=int, help="Maximum number of concurrent requests"
    )
    arg_parser.add_argument(
        "--socket-address",
        type=pathlib.Path,
        help="Unix Domain Socket address to listen on",
    )
    arg_parser.add_argument(
        "stdin", type=pathlib.Path, help="Initial stdin for the executor"
    )
    arg_parser.add_argument(
        "stdout", type=pathlib.Path, help="Initial stdout for the executor"
    )
    arg_parser.add_argument(
        "stderr", type=pathlib.Path, help="Initial stderr for the executor"
    )
    arg_parser.add_argument(
        "status_pipe",
        type=pathlib.Path,
        help="Where to write the executor setup's exit status",
    )
    arg_parser.add_argument(
        "command", nargs="*", help="Command to run when (re)starting the executor"
    )

    arg_result = arg_parser.parse_args(args)

    config_parser = ConfigParser()
    if arg_result.config_file:
        config_parser.read(arg_result.config_file)

    max_concurrency = arg_result.max_concurrency or config_parser.getint(
        "core", "max_concurrency", fallback=sys.maxsize
    )

    signal_mapping: dict[SupportedSignal, SupportedSignal] = dict()
    if config_parser.has_section("signal_translations"):
        for key, value in config_parser["signal_translations"].items():
            signal_mapping[SupportedSignal[key.upper()]] = SupportedSignal[
                value.upper()
            ]
    signal_translations = SignalTranslations(signal_mapping)

    executor_config = ExecutorConfig(
        arg_result.command or shlex.split(config_parser["executor"]["command"]),
        max_concurrency,
        signal_translations,
    )
    socket_address: Optional[str] = str(arg_result.socket_address) or config_parser.get(
        "core", "socket_address"
    )
    if not socket_address:
        raise RuntimeError("No socket address specified in args or config")

    return CommandServerConfig(
        socket_address=socket_address,
        executor_config=executor_config,
        initial_load_stdio=Stdio(
            str(arg_result.stdin),
            str(arg_result.stdout),
            str(arg_result.stderr),
            str(arg_result.status_pipe),
        ),
    )
