#!/bin/zsh

zmodload zsh/zutil
zmodload zsh/net/socket
zmodload -F zsh/stat b:zstat

function command-server-call() {
    setopt local_options local_traps err_return

    local -a fifos
    local -a pids
    local request_id result

    if [[ -t 0 ]]; then
        local saved_stty="$(stty -g)"
    fi

    () {
        trap '
            if [[ -t 0 ]]; then
                stty "$saved_stty"
            fi
            __command-server-cleanup
        ' EXIT

        local -a arg_background
        zparseopts -D -- \
            {b,-background}=arg_background

        local socket="$1"
        shift

        local backgrounded=""
        if [[ -n $arg_background ]]; then
            backgrounded=1
        fi

        local stdin stdout stderr status_pipe
        if [[ -n "$backgrounded" ]]; then
            __command-server-forward-stdio -b
        else
            local sig return_val
            for sig in TERM HUP; do
                return_val=$(($signals[(Ie)$sig] + 127))
                trap "
                    if [[ -n \"\$request_id\" ]]; then
                        command-server-sig '$socket' \"\$request_id\" '$sig'
                    fi
                    IFS= read result < \"\$status_pipe\"
                    return \$result
                " "$sig"
            done

            # TODO: how to get executor shell to accept INT and QUIT
            # https://unix.stackexchange.com/questions/614774/child-shell-script-didnt-respond-to-terminal-interrupt-sent-to-the-foreground-p
            # Mapping to TERM for now
            for sig in INT QUIT; do
                return_val=$(($signals[(Ie)$sig] + 127))
                trap "
                    if [[ -n \"\$request_id\" ]]; then
                        command-server-sig '$socket' \"\$request_id\" 'TERM'
                    fi
                    IFS= read result < \"\$status_pipe\"
                    return \$result
                " "$sig"
            done

            __command-server-forward-stdio
        fi

        __command-server-raw-send \
            "$socket" \
            call \
            "$PWD" \
            "$stdin" \
            "$stdout" \
            "$stderr" \
            "$status_pipe" \
            "$#" \
            "$@"

        if [[ -n $backgrounded ]]; then
            return 0
        else
            IFS="" read request_id < "$status_pipe"
            IFS="" read result < "$status_pipe"
            return $result
        fi
    } "$@"
}

function command-server-sig() {
    __command-server-raw-send \
        "$1" \
        sig \
        "$2" \
        "$3"
}

function command-server-reload() {
    setopt local_options local_traps err_return

    local -a fifos
    local -a pids

    if [[ -t 0 ]]; then
        local saved_stty="$(stty -g)"
    fi

    () {
        trap '
            if [[ -t 0 ]]; then
                stty "$saved_stty"
            fi
            __command-server-cleanup
        ' EXIT

        local -a arg_background
        zparseopts -D -- \
            {b,-background}=arg_background

        local socket="$1"
        shift

        local backgrounded=""
        if [[ -n $arg_background ]]; then
            backgrounded=1
        fi

        local stdin stdout stderr status_pipe
        if [[ -n "$backgrounded" ]]; then
            __command-server-forward-stdio -b
        else
            # TODO: what to do with signals
            __command-server-forward-stdio
        fi

        __command-server-raw-send \
            "$socket" \
            reload \
            "$stdin" \
            "$stdout" \
            "$stderr" \
            "$status_pipe"

        if [[ -n $backgrounded ]]; then
            return 0
        else
            IFS="" read result < "$status_pipe"
            return $result
        fi
    } "$@"
}

function command-server-start() {
    setopt local_options local_traps err_return

    local -a fifos
    local -a pids
    local server_pid

    if [[ -t 0 ]]; then
        # TODO do this even when stdin is redirected
        local saved_stty="$(stty -g)"
    fi

    () {
        trap '
            if [[ -t 0 ]]; then
                stty "$saved_stty"
            fi
            if [[ -n "$server_pid" ]]; then
                echo "Server is running at pid $server_pid"
            fi
            __command-server-cleanup
        ' EXIT

        local -a arg_background arg_concurrency arg_log_file
        zparseopts -D -- \
            {b,-background}=arg_background \
            -max-concurrency:=arg_concurrency \
            -log-file:=arg_log_file

        local socket="$1"
        shift

        local backgrounded=""
        if [[ -n $arg_background ]]; then
            backgrounded=1
        fi

        local max_concurrency="-1"
        if [[ -n $arg_concurrency ]]; then
            max_concurrency="$arg_concurrency[-1]"
        fi

        local log_file="/dev/null"
        if [[ -n $arg_log_file ]]; then
            log_file="$arg_log_file[-1]"
        fi

        local stdin stdout stderr status_pipe
        if [[ -n "$backgrounded" ]]; then
            __command-server-forward-stdio -b
        else
            # TODO: what to do with signals
            __command-server-forward-stdio
        fi

        ./command_server.py \
            "$socket" \
            "$max_concurrency" \
            "$stdin" \
            "$stdout" \
            "$stderr" \
            "$status_pipe" \
            "$@" &> "$log_file" &
        server_pid="$!"

        if [[ -n $backgrounded ]]; then
            return 0
        else
            IFS="" read result < "$status_pipe"
            return $result
        fi
    } "$@"

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

function __command-server-forward-stdio() {
    local backgrounded="$1"

    if [[ -z "$backgrounded" ]]; then
        status_pipe="$(mktemp -u)"
        fifos+=("$status_pipe")
        mkfifo -m 600 "$status_pipe"
    else
        status_pipe="/dev/null"
    fi

    local stdin_stat stdout_stat stderr_stat
    __command-server-fd-stat 0; stdin_stat="$REPLY"
    __command-server-fd-stat 1; stdout_stat="$REPLY"
    __command-server-fd-stat 2; stderr_stat="$REPLY"

    # Rules:
    #   - when backgrounded, do not forward TTYs
    #   - forward TTYs together
    #   - when stdout == stderr, forward those togehter
    #   - otherwise, forward separately
    local -A Reply
    if [[ "$stdin_stat" == "$stdout_stat" && "$stdin_stat" == "$stderr_stat" ]]; then
        # All stdio is on the same file
        __command-server-forward-fds "$backgrounded" 0 1 2
    elif [[ "$stdin_stat" == "$stdout_stat" ]]; then
        # in and out are the same, err is redirected
        __command-server-forward-fds "$backgrounded" 0 1
        __command-server-forward-fds "$backgrounded" 2
    elif [[ "$stdin_stat" == "$stderr_stat" ]]; then
        # in and err are the same, out is redirected
        __command-server-forward-fds "$backgrounded" 0 2
        __command-server-forward-fds "$backgrounded" 1
    elif [[ "$stdout_stat" == "$stderr_stat" ]]; then
        # out and err are the same, in is redirected
        __command-server-forward-fds "$backgrounded" 1 2
        __command-server-forward-fds "$backgrounded" 0
    else
        # all different
        __command-server-forward-fds "$backgrounded" 0
        __command-server-forward-fds "$backgrounded" 1
        __command-server-forward-fds "$backgrounded" 2
    fi

    stdin="$Reply[0]"
    stdout="$Reply[1]"
    stderr="$Reply[2]"
}

function __command-server-fd-stat() {
    local -A StatOutput
    zstat -H StatOutput -f "$1"
    REPLY="${StatOutput[inode]}:${StatOutput[rdev]}"
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
            local -a socat_args
            if [[ "${#fds}" -eq 1 && "$fds[1]" -eq 0 ]]; then
                socat_args+=("-u")
            elif [[ "$fds[1]" -ne 0 ]]; then
                socat_args+=("-U")
            fi

            local link="$(mktemp -u)"
            fifos+=("$link")
            socat_args+=(
                "GOPEN:$TTY,rawer,ignoreeof"
                "PTY,sane,link=$link"
            )

            socat "$socat_args[@]" &> log.txt &
            pids+=($!)

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

            pids+=($!)
            Reply[$fd]="$fifo"
        done
    fi
}
