#!/bin/sh

echo "Welcome to the eval executor!"

echo "Please write to stdin:"
WHAT_I_READ="$(cat)"

echo "Printing back on stderr:"
printf '%s\n' "$WHAT_I_READ" >&2

run_args_blindly () {
    "$@" &
}

echo "Entering the executor loop!"

set -- run_args_blindly "$@"
. "${COMMAND_SERVER_LIB}/posix-executor-loop.sh"
