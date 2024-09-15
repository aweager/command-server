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

exec < /dev/null > /dev/null 2>&1

exec 4> "$OUTPUT"

# Alert that loading was successful, and we can process requests
echo 0 >&4

exec 3< "$INPUT"

while true; do
    read_token; WORKING_DIR="$REPLY"
    read_token; STDIN="$REPLY"
    read_token; STDOUT="$REPLY"
    read_token; STDERR="$REPLY"
    read_token; STATUS_PIPE="$REPLY"
    read_token; NUM_ARGS="$REPLY"

    printf '%s\n' "$WORKING_DIR" "$STDIN" "$STDOUT" "$STDERR" "$STATUS_PIPE" "$NUM_ARGS"

    i=0
    set --
    while [ "$i" -lt "$NUM_ARGS" ]; do
        read_token
        set -- "$@" "$REPLY"
        : "$((i = i + 1))"
    done

    printf '%s\n' "$@"

    (
        exec 9> "$STATUS_PIPE"

        cd "$WORKING_DIR"
        "$EXECUTE_COMMAND" "$@" < "$STDIN" > "$STDOUT" 2> "$STDERR"
        CHILD_PID="$!"

        printf '%s\n' "$CHILD_PID" >&4

        wait "$CHILD_PID" > /dev/null 2>&1
        RESULT="$?"

        printf '%s\n' "$RESULT" >&9
    ) &

    if [ "$?" -ne 0 ]; then
        printf '%s\n' "-1" >&4
    fi
done
