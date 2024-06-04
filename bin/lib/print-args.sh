#!/bin/sh

execute_command () {
    echo "In working dir: $PWD" >&2
    echo "Executing command:"
    printf '    %s\n' "$@"

    "$@"
}

source "lib/posix-executor-loop.sh"
