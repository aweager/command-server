#!/bin/zsh

zmodload zsh/net/socket
zmodload -F zsh/stat b:zstat

function command-server-call-and-forget() {
    setopt local_options err_return

    if [[ $# -lt 2 ]]; then
        printf '%s\n' \
            'Usage: command-server-call-and-forget <socket> <command> [<args>...]' >&2
        return 1
    fi

    local socket="$1"
    shift

    local stdin stdout stderr
    __command-server-forward-stdio-no-tty

    __command-server-raw-send \
        "$socket" \
        call \
        "$PWD" \
        "$stdin" \
        "$stdout" \
        "$stderr" \
        "/dev/null" \
        "$#" \
        "$@"
}

function __command-server-raw-send() {
    setopt local_options err_return

    local send_fd

    {
        local socket="$1"
        zsocket "$socket"
        send_fd="$REPLY"
        shift

        local -a escaped_tokens=()
        local token
        local newline=$'\n'
        for token; do
            token="${token//\\/\\\\}"
            token="${token//${newline}/\\n}"
            escaped_tokens+=( "$token" )
        done

        printf '%s\n' "$escaped_tokens[@]" >&$send_fd
    } always {
        if [[ -n "$send_fd" ]]; then
            exec {send_fd}>&-
        fi
    }
}

function __command-server-forward-stdio-no-tty() {
    # Rules:
    #   - don't forward TTYs (this is a background operation)
    #       - handled in __command-server-forward-pipe
    #   - forward stdin on its own
    #   - when stdout == stderr, forward those togehter
    #       - that way order of writes is maintained

    __command-server-forward-pipe -u 0
    stdin="$REPLY"

    local stdout_stat stderr_stat
    __command-server-fd-stat 1; stdout_stat="$REPLY"
    __command-server-fd-stat 2; stderr_stat="$REPLY"

    if [[ "$stdout_stat" == "$stderr_stat" ]]; then
        __command-server-forward-pipe -U 1
        stdout="$REPLY"
        stderr="$REPLY"
    else
        __command-server-forward-pipe -U 1
        stdout="$REPLY"
        __command-server-forward-pipe -U 2
        stderr="$REPLY"
    fi
}

function __command-server-fd-stat() {
    local -A StatOutput
    zstat -H StatOutput -f "$1"
    REPLY="${StatOutput[inode]}:${StatOutput[rdev]}"
}

function __command-server-forward-pipe() {
    if [[ -t $2 ]]; then
        # do not forward TTYs
        REPLY="/dev/null"
        return
    fi

    # Create the fifo ourselves so we don't have process scheduling race
    # conditions (it needs to exist when the server gets the request)
    REPLY="$(mktemp -u)"
    mkfifo -m 600 "$REPLY"
    if [[ "$1" == "-u" ]]; then
        (
            setopt no_err_return
            socat "$1" "FD:3" "PIPE:$REPLY"
            rm "$REPLY"
        ) 3<&$2 < /dev/null &> /dev/null &!
    else
        (
            setopt no_err_return
            socat "$1" "FD:3" "PIPE:$REPLY"
            rm "$REPLY"
        ) 3>&$2 < /dev/null &> /dev/null &!
    fi
}
