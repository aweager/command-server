#!/bin/sh

# Takes four positional arguments:
#   1: the command to use to dispatch requests
#   2: the pipe to read commands from
#   3: the pipe to write pids to
#   4: the pipe to write completion messages to
#
# This script will close FD 0, 1, 2, and replace them.

# Reads a newline-terminated token, handling \\ and \n escape sequences
read_token () {
    # First sed command handles \n at start of the line
    # Second handles \n when not preceded by \
    # Third handles \\
    IFS= read -r REPLY <&3
    REPLY="$( \
        printf '%s' "$REPLY" | \
            sed -e 's ^\\n \n ' \
                -e 's \([^\\]\)\\n \1\n g' \
                -e 's \\\\ \\ g';
        echo x)"
    REPLY="${REPLY%?}"
}

EXECUTE_COMMAND="$1"
INPUT="$2"
OUTPUT="$3"
QUEUE_OPS_FIFO="$4"

exec < /dev/null > /dev/null 2>&1

exec 3< "$INPUT" 4> "$OUTPUT" 5> "$QUEUE_OPS_FIFO"

# Alert that loading was successful, and we can process requests
echo 0 > "$OUTPUT"

while true; do
    read_token; REQUEST_ID="$REPLY"
    read_token; WORKING_DIR="$REPLY"
    read_token; STDIN="$REPLY"
    read_token; STDOUT="$REPLY"
    read_token; STDERR="$REPLY"
    read_token; STATUS_PIPE="$REPLY"
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
        "$EXECUTE_COMMAND" "$@" < "$STDIN" > "$STDOUT" 2> "$STDERR" &
        CHILD_PID="$!"

        printf '%s\n' "$CHILD_PID" >&4

        wait "$CHILD_PID" > /dev/null 2>&1
        RESULT="$?"

        printf '%s\n' "done $REQUEST_ID" >&5
        printf '%s\n' "$RESULT" > "$STATUS_PIPE"
    ) &

    if [[ "$?" -ne 0 ]]; then
        printf '%s\n' "-1" >&4
    fi
done
