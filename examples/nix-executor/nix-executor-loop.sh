#!/bin/sh

run_args_blindly () {
    "$@" <&0 >&1 2>&2 &
}

export COMMAND_SERVER_LIB="$1"
shift

set -- run_args_blindly "$@"
. "${COMMAND_SERVER_LIB}/posix-executor-loop.sh"
