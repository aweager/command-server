#!/bin/sh

# Takes 3 positional arguments:
#   1: the command to use to dispatch requests
#   2: the pipe to read commands from
#   3: the pipe to write pids to
#
# This script will close FD 0, 1, 2, and replace them.

# Reads a newline-terminated token, handling \\ and \n escape sequences
read_token () {
    IFS= read -r REPLY <&3

    # First sed command handles \n preceded by an odd number of \ and the start of the line
    # Second handles \n when preceded by an odd number of \
    # Third handles \\
    REPLY="$( \
        printf '%s' "$REPLY" | \
            sed -e 's ^\(\(\\\\\)*\)\\n \1\n ' \
                -e 's \([^\\]\)\(\(\\\\\)*\)\\n \1\2\n g' \
                -e 's \\\\ \\ g';
        echo x)"
    REPLY="${REPLY%?}"
}

EXECUTE_COMMAND="$1"
INPUT="$2"
OUTPUT="$3"
QUEUE_OPS_FIFO="$4"

exec < /dev/null > /dev/null 2>&1

exec 3< "$INPUT" 4> "$OUTPUT"

# Alert that loading was successful, and we can process requests
echo 0 > "$OUTPUT"

while true; do
    read_token; REQUEST_ID="$REPLY"
    read_token; WORKING_DIR="$REPLY"
    read_token; STDIN="$REPLY"
    read_token; STDOUT="$REPLY"
    read_token; STDERR="$REPLY"
    read_token; STATUS_PIPE="$REPLY"
    read_token; COMPLETION_FIFO="$REPLY"
    read_token; NUM_ARGS="$REPLY"

    i=1
    read_token
    set -- "$REPLY"
    while [ "$i" -lt "$NUM_ARGS" ]; do
        read_token
        set -- "$@" "$REPLY"
        : "$((i = i + 1))"
    done

    (
        cd "$WORKING_DIR"
        "$EXECUTE_COMMAND" "$@" < "$STDIN" > "$STDOUT" 2> "$STDERR" 9> "$COMPLETION_FIFO"
        CHILD_PID="$!"

        printf '%s\n' "$CHILD_PID" >&4

        wait "$CHILD_PID" > /dev/null 2>&1
        RESULT="$?"

        printf '%s\n' "$RESULT" > "$STATUS_PIPE"
    ) &

    if [ "$?" -ne 0 ]; then
        printf '%s\n' "-1" >&4
    fi
done
