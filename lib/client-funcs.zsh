#!/bin/zsh

0="${ZERO:-${${0:#$ZSH_ARGZERO}:-${(%):-%N}}}"
0="${${(M)0:#/*}:-$PWD/$0}"

typeset -gH COMMAND_SERVER_LIB="${0:a:h}"

zmodload zsh/zutil
zmodload zsh/net/socket
zmodload -F zsh/stat b:zstat

function command-server-call-and-forget() {
    setopt local_options local_traps err_return

    local -a fifos
    local -a pids

    () {
        trap '
            __command-server-cleanup
        ' EXIT

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
    } "$@"
}

function command-server-sig() {
    __command-server-raw-send \
        "$1" \
        sig \
        "$2" \
        "$3"
}

function __command-server-raw-send() {
    setopt local_options local_traps err_return

    local send_fd

    () {
        trap '
            if [[ -n "$send_fd" ]]; then
                exec {send_fd}>&-
                send_fd=""
            fi
        ' EXIT

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
    } "$@"
}

function __command-server-cleanup() {
    trap '
        local pid
        for pid in "$pids[@]"; do
            kill -HUP "$pid" &> /dev/null || true
        done

        local fifo
        for fifo in "$fifos[@]"; do
            if [[ -e $fifo ]]; then
                rm "$fifo"
            fi
        done
    ' EXIT
}

function __command-server-forward-stdio-no-tty() {
    # Rules:
    #   - don't forward TTYs (this is a background operation)
    #       - handled in __command-server-forward-pipe
    #   - forward stdin on its own
    #   - when stdout == stderr, forward those togehter
    #       - that way order of writes is maintained

    __command-server-forward-pipe -u 0

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
            socat "$1" "FD:3" "GOPEN:$REPLY"
            rm "$REPLY"
        ) 3<&$2 < /dev/null &> /dev/null &
    else
        (
            setopt no_err_return
            socat "$1" "FD:3" "PIPE:$REPLY"
            rm "$REPLY"
        ) 3>&$2 < /dev/null &> /dev/null &
    fi
}

function __command-server-forward-fds() {
    local backgrounded="$1"
    shift
    local -a fds=("$@")

    local fd

    if [[ -t "$fds[1]" ]]; then
        if [[ -n "$backgrounded" ]]; then
            for fd in "$fds[@]"; do
                Reply[$fd]="/dev/null"
            done
        else
            # TODO - the below works in a subprocess but not as a function
            #for fd in "$fds[@]"; do
            #    Reply[$fd]="$TTY"
            #done
            local -a socat_args
            if [[ "${#fds}" -eq 1 && "$fds[1]" -eq 0 ]]; then
                socat_args+=("-u")
            elif [[ "$fds[1]" -ne 0 ]]; then
                socat_args+=("-U")
            fi

            local link="$(mktemp -u)"
            socat_args+=(
                "GOPEN:$TTY,rawer,ignoreeof"
                "PTY,sane,link=$link"
            )

            socat "$socat_args[@]" &> /dev/null &!

            for fd in "$fds[@]"; do
                Reply[$fd]="$link"
            done

            while [[ ! -e "$link" ]]; do
                sleep 0.01
            done

            stty brkint -ignbrk isig < "$TTY"
        fi
    else
        local direction fifo
        for fd in "$fds[@]"; do

            fifo="$(mktemp -u)"
            fifos+=("$fifo")
            mkfifo -m 600 "$fifo"

            if [[ "$fd" -eq 0 ]]; then
                socat -u "FD:$fd" "GOPEN:$fifo" &> /dev/null &
            else
                socat -U "FD:3" "GOPEN:$fifo" 3>&$fd &> /dev/null &
            fi

            Reply[$fd]="$fifo"
        done
    fi
}
