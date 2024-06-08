#!/bin/sh

execute_command () {
    echo "In working dir: $PWD" >&2
    echo "Executing command:"
    printf '    %s\n' "$@"

    for sig in INT TERM HUP QUIT; do
        trap "
            echo 'print-args got $sig' >> log.txt
            if [ -n \"\$CHILD_PID\" ]; then
                kill -s '$sig' \"\$CHILD_PID\"
                wait \"\$CHILD_PID\"
                exit \$?
            else
                exit 14
            fi
        " "$sig"
    done

    "$@"
    #CHILD_PID="$!"
    #wait "$CHILD_PID"
    exit $?
}

echo "stdin contains:"
cat

echo "stderr" >&2

set -- execute_command "$@"
. "lib/posix-executor-loop.sh"
