#!/bin/zsh

zmodload zsh/net/socket
zmodload -F zsh/stat b:zstat

typeset -gAH CommandServerClient

CommandServerClient[rundir]="${XDG_RUNTIME_DIR-${HOME}/.cache}/command-server-client"
mkdir -p "$CommandServerClient[rundir]"
chmod 0700 "$CommandServerClient[rundir]"

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
    local invocation_id="$RANDOM"
    local -a pids fifos
    __command-server-forward-stdio-no-tty

    if ! __command-server-raw-send \
        "$socket" \
        call \
        "$PWD" \
        "$stdin" \
        "$stdout" \
        "$stderr" \
        "/dev/null" \
        "$#" \
        "$@"; then

        local pid
        for pid in "$pids[@]"; do
            kill -HUP "$pid" &> /dev/null || true
        done

        local fifo
        for fifo in "$fifos[@]"; do
            if [[ -e $fifo ]]; then
                rm "$fifo" &> /dev/null || true
            fi
        done

        return 1
    fi
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
    local direction="$1"
    local fd="$2"

    if [[ -t $fd ]]; then
        # do not forward TTYs
        REPLY="/dev/null"
        return
    fi

    # Create the fifo ourselves so we don't have process scheduling race
    # conditions (it needs to exist when the server gets the request)
    REPLY="${CommandServerClient[rundir]}/$$.$invocation_id.$fd.pipe"
    mkfifo -m 600 "$REPLY"
    fifos+=("$REPLY")
    if [[ "$direction" == "-u" ]]; then
        (
            setopt no_err_return
            socat "$direction" "FD:3" "PIPE:$REPLY"
            rm "$REPLY"
        ) 3<&$fd < /dev/null &> /dev/null &!
    else
        (
            setopt no_err_return
            socat "$direction" "FD:3" "PIPE:$REPLY"
            rm "$REPLY"
        ) 3>&$fd < /dev/null &> /dev/null &!
    fi
    pids+=($!)
}
