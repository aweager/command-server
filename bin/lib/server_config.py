from configparser import ConfigParser
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
import logging
import os
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
    working_dir: str
    command: list[str]
    max_concurrency: int
    signal_translations: SignalTranslations


@dataclass
class CommandServerConfig:
    log_level: int
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
        if input_path.is_absolute() or self.dir is None:
            return input_path

        return self.dir.joinpath(input_path)


class _ArgNamespace(Namespace):
    config_file: Optional[pathlib.Path]
    max_concurrency: Optional[int]
    socket_address: Optional[pathlib.Path]
    stdin: pathlib.Path
    stdout: pathlib.Path
    stderr: pathlib.Path
    status_pipe: pathlib.Path
    command: list[str]


def _parse_args(argv: list[str]) -> _ArgNamespace:
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
    arg_parser.add_argument("--log-level", help="Log level, defaults to WARNING")
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

    return arg_parser.parse_args(argv[1:], _ArgNamespace())


@dataclass
class _ConfigFile:
    # [core]
    socket_address: Optional[pathlib.Path] = None
    max_concurrency: Optional[int] = None
    log_level: Optional[str] = None

    # [executor]
    working_dir: Optional[pathlib.Path] = None
    command: Optional[list[str]] = None

    # [signal_translations]
    signal_translations: Optional[SignalTranslations] = None


def _parse_file(path: Optional[pathlib.Path]):
    if not path:
        return _ConfigFile()

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

    command: Optional[list[str]]
    match config_parser.get("executor", "command", fallback=None):
        case str() as command_str:
            command = shlex.split(command_str)
        case _:
            command = None

    return _ConfigFile(
        signal_translations=signal_translations,
        command=command,
        max_concurrency=config_parser.getint("core", "max_concurrency", fallback=None),
        log_level=config_parser.get("core", "log_level", fallback=None),
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

    socket_address = args.socket_address or file.socket_address
    if not socket_address:
        raise RuntimeError("No socket address specified in args or config file")

    command = args.command or file.command
    if not command:
        raise RuntimeError("No executor command specified in args or config file")

    return CommandServerConfig(
        socket_address=str(socket_address),
        log_level=logging.getLevelNamesMapping()[
            args.log_level or file.log_level or "WARNING"
        ],
        executor_config=ExecutorConfig(
            command=command,
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
