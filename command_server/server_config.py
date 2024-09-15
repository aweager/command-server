import logging
import os
import pathlib
import shlex
from argparse import ArgumentParser, Namespace
from configparser import ConfigParser
from dataclasses import dataclass

from result import Err, Ok, Result

from .api import ExecutorConfigOverrides, Signal
from .errors import InvalidExecutorConfig

_LOGGER = logging.getLogger(__name__)


@dataclass
class SignalTranslator:
    mapping: dict[Signal, Signal]

    def translate(self, sig: Signal) -> Signal:
        if sig in self.mapping:
            return self.mapping[sig]
        return sig


@dataclass
class ExecutorConfig:
    cwd: pathlib.Path
    command: str
    args: list[str]
    signal_translator: SignalTranslator


@dataclass
class BaseExecutorConfig:
    cwd: pathlib.Path | None
    command: str
    args: list[str]
    signal_translator: SignalTranslator

    def apply_overrides(
        self,
        overrides: ExecutorConfigOverrides,
    ) -> Result[ExecutorConfig, InvalidExecutorConfig]:
        cwd = pathlib.Path(overrides.cwd) if overrides.cwd is not None else self.cwd
        if cwd is None:
            return Err(InvalidExecutorConfig("cwd must be specified"))

        args = overrides.args if overrides.args is not None else self.args

        return Ok(
            ExecutorConfig(
                cwd=cwd,
                command=self.command,
                args=args,
                signal_translator=self.signal_translator,
            )
        )


@dataclass
class CommandServerConfig:
    log_level: int
    log_file: str
    socket_path: pathlib.Path
    base_executor_config: BaseExecutorConfig


@dataclass
class _ConfigFilePath:
    dir: pathlib.Path | None

    def maybe_relative(self, path_str: str | None) -> pathlib.Path | None:
        if not path_str:
            return None

        input_path = pathlib.Path(path_str).expanduser()

        if path_str.startswith("./") and self.dir:
            return self.dir.joinpath(input_path)

        return input_path


class _ArgNamespace(Namespace):
    config_file: pathlib.Path | None
    log_file: pathlib.Path | None
    log_level: str | None
    socket: pathlib.Path | None
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
        "socket",
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

    return arg_parser.parse_args(argv[1:], _ArgNamespace())


@dataclass
class _ConfigFile:
    # [core]
    max_concurrency: int | None = None
    log_level: str | None = None
    log_file: pathlib.Path | None = None

    # [executor]
    working_dir: pathlib.Path | None = None
    command: str | None = None
    args: list[str] | None = None

    # [signal_translations]
    signal_translations: SignalTranslator | None = None


def _parse_file(path: pathlib.Path | None):
    if not path:
        return _ConfigFile()

    config_parser = ConfigParser()
    config_parser.read(path)
    config_dir = _ConfigFilePath(path.parent)

    signal_translations: SignalTranslator | None = None
    if config_parser.has_section("signal_translations"):
        signal_mapping: dict[Signal, Signal] = dict()
        for key, value in config_parser["signal_translations"].items():
            signal_mapping[Signal[key.upper()]] = Signal[value.upper()]
        signal_translations = SignalTranslator(signal_mapping)

    command: str | None
    match config_parser.get("executor", "command", fallback=None):
        case str() as command_str:
            if command_str.startswith("./"):
                command = str(config_dir.maybe_relative(command_str).absolute())  # type: ignore
            else:
                command = command_str
        case _:
            command = None

    args: list[str] | None
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
        log_file=config_dir.maybe_relative(config_parser.get("core", "log_file", fallback=None)),
        working_dir=config_dir.maybe_relative(
            config_parser.get("executor", "working_dir", fallback=None)
        ),
    )


def parse_config(argv: list[str]) -> CommandServerConfig:
    args = _parse_args(argv)
    file = _parse_file(args.config_file)

    socket_path = args.socket
    if not socket_path:
        raise RuntimeError("No socket address specified in args or config file")

    if not file.command:
        raise RuntimeError("No executor command specified in config file")

    return CommandServerConfig(
        socket_path=socket_path,
        log_level=logging.getLevelNamesMapping()[args.log_level or file.log_level or "WARNING"],
        log_file=str(args.log_file or file.log_file or "/dev/null"),
        base_executor_config=BaseExecutorConfig(
            cwd=pathlib.Path(file.working_dir or os.getcwd()),
            command=file.command,
            args=args.executor_args or file.args or [],
            signal_translator=file.signal_translations or SignalTranslator(dict()),
        ),
    )
