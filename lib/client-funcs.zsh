#!/bin/zsh

zmodload zsh/net/socket
zmodload -F zsh/stat b:zstat

typeset -gAH CommandServerClient

CommandServerClient[rundir]="${XDG_RUNTIME_DIR-${HOME}/.cache}/command-server-client"
mkdir -p "$CommandServerClient[rundir]"
chmod 0700 "$CommandServerClient[rundir]"

CommandServerClient[logdir]="${XDG_STATE_DIR-${HOME}/.local/state}/command-server-client"
mkdir -p "$CommandServerClient[logdir]"

() {
    local -A StatOutput
    zstat -H StatOutput /dev/null
    CommandServerClient[devnull]="${StatOutput[inode]}:${StatOutput[rdev]}"
}

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

    printf '%s.%s %s forget %s\n' "$$" "$invocation_id" "$socket" "$*" >> "$CommandServerClient[logdir]/client.log"

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
    #   - forward in fds and out fds separately
    #   - forward together when possible
    #       - that way order of writes is maintained

    local -A Reply
    __command-server-forward-pipes -u 0
    __command-server-forward-pipes -U 1 2
    stdin="$Reply[0]"
    stdout="$Reply[1]"
    stderr="$Reply[2]"
}

function __command-server-fd-stat() {
    local -A StatOutput
    zstat -H StatOutput -f "$1"
    REPLY="${StatOutput[inode]}:${StatOutput[rdev]}"
}

function __command-server-forward-pipes() {
    local direction="$1"
    shift

    local -A ReplyByStat
    local fd fd_stat fifo
    for fd; do
        fd_stat="$(__command-server-fd-stat $fd)"

        if [[ -n "$ReplyByStat[$fd_stat]" ]]; then
            Reply[$fd]="$ReplyByStat[$fd_stat]"
        elif [[ -t $fd || "$fd_stat" == "$CommandServerClient[devnull]" ]]; then
            ReplyByStat[$fd_stat]=/dev/null
            Reply[$fd]=/dev/null
        else
            fifo="${CommandServerClient[rundir]}/$$.$invocation_id.$fd.pipe"
            fifos+=("$fifo")
            mkfifo -m 600 "$fifo"

            ReplyByStat[$fd_stat]="$fifo"
            Reply[$fd]="$fifo"

            if [[ "$direction" == "-u" ]]; then
                (
                    setopt no_err_return
                    socat "$direction" "FD:3" "PIPE:$fifo"
                    rm "$fifo"
                ) 3<&$fd < /dev/null &> /dev/null &!
            else
                (
                    setopt no_err_return
                    socat "$direction" "FD:3" "PIPE:$fifo"
                    rm "$fifo"
                ) 3>&$fd < /dev/null &> /dev/null &!
            fi
            pids+=($!)
        fi
    done
}
