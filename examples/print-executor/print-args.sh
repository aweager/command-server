#!/bin/sh

execute_command () {
    (
        trap '
            echo "print-args got TERM" >&2
            if [ -n "$CHILD_PID" ]; then
                kill -s TERM "$CHILD_PID"
                wait "$CHILD_PID"
                exit $?
            else
                exit 143
            fi
        ' TERM

        trap '
            echo "print-args got HUP" >&2
            if [ -n "$CHILD_PID" ]; then
                kill -s HUP "$CHILD_PID"
                wait "$CHILD_PID"
                exit $?
            else
                exit 129
            fi
        ' HUP

        echo "In working dir: $PWD" >&2
        echo "Received command:"
        printf '    %s\n' "$@"
    ) &
}

echo "Welcome to the print executor!"
echo "Executing cat:"
cat

set -- execute_command "$@"
. "${COMMAND_SERVER_LIB}/posix-executor-loop.sh"
