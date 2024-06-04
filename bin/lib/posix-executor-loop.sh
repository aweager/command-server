#!/bin/sh
# Expects execute_command to be defined in the environment

exec <coproc_in >coproc_out 2>>tmp.txt

# Reads a newline-terminated token, handling \\ and \n escape sequences
read_token () {
    # First sed command handles \n at start of the line
    # Second handles \n when not preceded by \
    # Third handles \\
    IFS= read -r REPLY
    printf "Read raw token %s\n" "$REPLY" >&2
    REPLY="$( \
        printf '%s' "$REPLY" | \
            sed -e 's ^\\n \n ' \
                -e 's \([^\\]\)\\n \1\n g' \
                -e 's \\\\ \\ g';
        echo x)"
    REPLY="${REPLY%?}"
}

read_token; QUEUE_OPS_FIFO="$REPLY"

while true; do
    read_token; REQUEST_ID="$REPLY"
    read_token; WORKING_DIR="$REPLY"
    read_token; STDIN="$REPLY"
    read_token; STDOUT="$REPLY"
    read_token; STDERR="$REPLY"
    read_token; RESPONSE_PIPE="$REPLY"
    read_token; NUM_ARGS="$REPLY"

    i=1
    read_token
    set -- "$REPLY"
    while [ "$i" -lt "$NUM_ARGS" ]; do
        read_token
        set -- "$@" "$REPLY"
        : "$((i = i + 1))"
    done

    echo "Executing work item:" >&2
    printf '    %s\n' "$REQUEST_ID" "$WORKING_DIR" "$STDIN" "$STDOUT" "$STDERR" "$RESPONSE_PIPE" "$NUM_ARGS" "$@" >&2

    (
        cd "$WORKING_DIR" && (execute_command "$@")
        printf '%s\n' "$?" > "$RESPONSE_PIPE"
        printf '%s\n' "done $REQUEST_ID" > "$QUEUE_OPS_FIFO"
    ) < "$STDIN" > "$STDOUT" 2> "$STDERR" &

    printf '%s\n' "$!"
done
