import logging
import os
import pathlib
import shlex
import sys
from argparse import ArgumentParser, Namespace
from configparser import ConfigParser
from dataclasses import dataclass
from typing import Optional

from .model import Stdio, SupportedSignal

_LOGGER = logging.getLogger(__name__)


@dataclass
class SignalTranslations:
    mapping: dict[SupportedSignal, SupportedSignal]


@dataclass
class ExecutorConfig:
    working_dir: str
    command: str
    args: list[str]
    max_concurrency: int
    signal_translations: SignalTranslations


@dataclass
class CommandServerConfig:
    log_level: int
    log_file: str
    socket_address: str
    initial_load_stdio: Stdio
    executor_config: ExecutorConfig


@dataclass
class _ConfigFilePath:
    dir: Optional[pathlib.Path]

    def maybe_relative(self, path_str: Optional[str]) -> Optional[pathlib.Path]:
        if not path_str:
            return None

        input_path = pathlib.Path(path_str).expanduser()

        if path_str.startswith("./") and self.dir:
            return self.dir.joinpath(input_path)

        return input_path


class _ArgNamespace(Namespace):
    config_file: Optional[pathlib.Path]
    log_file: Optional[pathlib.Path]
    log_level: Optional[str]
    max_concurrency: Optional[int]
    socket: Optional[pathlib.Path]
    stdin: pathlib.Path
    stdout: pathlib.Path
    stderr: pathlib.Path
    status_pipe: pathlib.Path
    executor_args: list[str]


def _parse_args(argv: list[str]) -> _ArgNamespace:
    arg_parser = ArgumentParser(
        prog="command_server.py",
        description="Server to run commands in a different environment",
        epilog="See http://www.github.com/aweager/command-server for details",
    )

    arg_parser.add_argument("--log-level", help="Log level, defaults to WARNING")
    arg_parser.add_argument(
        "--log-file",
        type=pathlib.Path,
        help="Log file",
    )
    arg_parser.add_argument(
        "--max-concurrency", type=int, help="Maximum number of concurrent requests"
    )
    arg_parser.add_argument(
        "--socket",
        type=pathlib.Path,
        help="Unix Domain Socket address to listen on",
    )

    arg_parser.add_argument(
        "config_file",
        type=pathlib.Path,
        help="Configuration file to base the server on",
    )
    arg_parser.add_argument(
        "executor_args",
        nargs="*",
        help="Arguments to pass when (re)starting the executor",
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

    return arg_parser.parse_args(argv[1:], _ArgNamespace())


@dataclass
class _ConfigFile:
    # [core]
    socket_address: Optional[pathlib.Path]
    max_concurrency: Optional[int]
    log_level: Optional[str]
    log_file: Optional[pathlib.Path]

    # [executor]
    working_dir: Optional[pathlib.Path]
    command: Optional[str]
    args: Optional[list[str]]

    # [signal_translations]
    signal_translations: Optional[SignalTranslations]


def _parse_file(path: Optional[pathlib.Path]):
    if not path:
        return _ConfigFile(None, None, None, None, None, None, None, None)

    config_parser = ConfigParser()
    config_parser.read(path)
    config_dir = _ConfigFilePath(path.parent)

    signal_translations: Optional[SignalTranslations] = None
    if config_parser.has_section("signal_translations"):
        signal_mapping: dict[SupportedSignal, SupportedSignal] = dict()
        for key, value in config_parser["signal_translations"].items():
            signal_mapping[SupportedSignal[key.upper()]] = SupportedSignal[
                value.upper()
            ]
        signal_translations = SignalTranslations(signal_mapping)

    command: Optional[str]
    match config_parser.get("executor", "command", fallback=None):
        case str() as command_str:
            if command_str.startswith("./"):
                command = str(config_dir.maybe_relative(command_str).absolute())  # type: ignore
            else:
                command = command_str
        case _:
            command = None

    args: Optional[list[str]]
    match config_parser.get("executor", "args", fallback=None):
        case str() as args_str:
            args = shlex.split(args_str)
        case _:
            args = None

    return _ConfigFile(
        signal_translations=signal_translations,
        command=command,
        args=args,
        max_concurrency=config_parser.getint("core", "max_concurrency", fallback=None),
        log_level=config_parser.get("core", "log_level", fallback=None),
        log_file=config_dir.maybe_relative(
            config_parser.get("core", "log_file", fallback=None)
        ),
        socket_address=config_dir.maybe_relative(
            config_parser.get("core", "socket_address", fallback=None)
        ),
        working_dir=config_dir.maybe_relative(
            config_parser.get("executor", "working_dir", fallback=None)
        ),
    )


def parse_config(argv: list[str]) -> CommandServerConfig:
    args = _parse_args(argv)
    file = _parse_file(args.config_file)

    socket_address = args.socket or file.socket_address
    if not socket_address:
        raise RuntimeError("No socket address specified in args or config file")

    if not file.command:
        raise RuntimeError("No executor command specified in config file")

    return CommandServerConfig(
        socket_address=str(socket_address),
        log_level=logging.getLevelNamesMapping()[
            args.log_level or file.log_level or "WARNING"
        ],
        log_file=str(args.log_file or file.log_file or "/dev/null"),
        executor_config=ExecutorConfig(
            command=file.command,
            args=args.executor_args or file.args or [],
            working_dir=str(file.working_dir or os.getcwd()),
            max_concurrency=args.max_concurrency or file.max_concurrency or sys.maxsize,
            signal_translations=file.signal_translations or SignalTranslations(dict()),
        ),
        initial_load_stdio=Stdio(
            str(args.stdin),
            str(args.stdout),
            str(args.stderr),
            str(args.status_pipe),
        ),
    )
