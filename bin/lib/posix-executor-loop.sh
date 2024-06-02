#!/bin/sh

# Expects execute-command to be defined in the environment

null-delim-read () {
    # TODO do this without -d option, which isn't POSIX-compliant
    IFS="" read -rd $'\0' "$1"
    eval "echo \"read a line: $1 = \$$1\"" >> tmp.txt
}

QUEUE_OPS_FIFO=""
null-delim-read QUEUE_OPS_FIFO

while true; do
    REQUEST_ID=""
    WORKING_DIR=""
    STDIN=""
    STDOUT=""
    STDERR=""
    RESPONSE_PIPE=""
    COMMAND=""
    null-delim-read REQUEST_ID
    null-delim-read WORKING_DIR
    null-delim-read STDIN
    null-delim-read STDOUT
    null-delim-read STDERR
    null-delim-read RESPONSE_PIPE
    null-delim-read COMMAND

    (
        cd "$WORKING_DIR" && execute-command "$COMMAND"
        printf '%s\n' "$?" > "$RESPONSE_PIPE"
        printf '%s\n' "done $REQUEST_ID" > "$QUEUE_OPS_FIFO"
    ) < "$STDIN" > "$STDOUT" 2> "$STDERR" &

    printf '%s\n' "$!"
done
