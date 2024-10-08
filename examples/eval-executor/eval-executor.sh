#!/bin/sh

echo "Welcome to the eval executor!"

echo "Please write to stdin:"
WHAT_I_READ="$(cat)"

echo "Printing back on stderr:"
printf '%s\n' "$WHAT_I_READ" >&2

run_args_blindly () {
    echo "Evaluating:"
    printf '    %s\n' "$@"
    echo

    "$@" <&0 >&1 2>&2 &
}

echo "Entering the executor loop!"
echo "Will overwrite"
tput cuu1
sleep 1
echo "Overwritten"

set -- run_args_blindly "$@"
. "${COMMAND_SERVER_LIB}/posix-executor-loop.sh"
