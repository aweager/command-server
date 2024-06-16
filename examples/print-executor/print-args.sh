#!/bin/sh

execute_command () {
    (
        echo "In working dir: $PWD" >&2
        echo "Executing command:"
        printf '    %s\n' "$@"

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

        exec "$@"
    ) &
}

echo "stdin contains:"
cat

echo "stderr" >&2

set -- execute_command "$@"
. "lib/posix-executor-loop.sh"
