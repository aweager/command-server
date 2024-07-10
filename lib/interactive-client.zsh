#!/bin/zsh

typeset -gH COMMAND_SERVER_LIB="${0:a:h}"

zmodload zsh/net/socket
zmodload -F zsh/stat b:zstat

source "$COMMAND_SERVER_LIB/client-funcs.zsh"

function command-server-call() {
    setopt local_options local_traps err_return

    if [[ $# -lt 2 ]]; then
        printf '%s\n' \
            'Usage: command-server-call <socket> <command> [<args>...]' >&2
        return 1
    fi

    local -a fifos
    local -a pids
    local request_id result

    local saved_tty
    if [[ -t 0 ]]; then
        saved_stty="$(stty -g)"
    fi

    () {
        trap __command-server-cleanup EXIT

        local socket="$1"
        shift

        local stdin stdout stderr status_pipe
        local sig sig_return_val
        for sig in INT TERM QUIT HUP; do
            sig_return_val="$((127 + $signals[(Ie)$sig]))"
            trap "
                if [[ -n \"\$result\" ]]; then
                    return \$result
                elif [[ -n \"\$request_id\" ]]; then
                    command-server-sig '$socket' \"\$request_id\" '$sig'
                    IFS= read result < \"\$status_pipe\"
                    return \$result
                else
                    return $sig_return_val
                fi
            " "$sig"
        done

        local invocation_id="$RANDOM"
        __command-server-forward-stdio-yes-tty

        printf '%s.%s %s call %s\n' "$$" "$invocation_id" "$socket" "$*" >> "$CommandServerClient[logdir]/client.log"

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

        IFS="" read request_id < "$status_pipe"
        IFS="" read result < "$status_pipe"
        return $result
    } "$@"
}

function command-server-reload() {
    setopt local_options local_traps err_return

    if [[ $# -ne 1 ]]; then
        printf '%s\n' \
            'Usage: command-server-reload <socket>' >&2
        return 1
    fi

    local -a fifos
    local -a pids
    local saved_stty

    if [[ -t 0 ]]; then
        saved_stty="$(stty -g)"
    fi

    () {
        trap __command-server-cleanup EXIT

        local socket="$1"
        local stdin stdout stderr status_pipe

        # TODO signals
        local invocation_id="$RANDOM"
        __command-server-forward-stdio-yes-tty

        printf '%s.%s %s reload %s\n' "$$" "$invocation_id" "$socket" "$*" >> "$CommandServerClient[logdir]/client.log"

        __command-server-raw-send \
            "$socket" \
            reload \
            "$stdin" \
            "$stdout" \
            "$stderr" \
            "$status_pipe"

        IFS="" read result < "$status_pipe"
        return $result
    } "$@"
}

function command-server-start() {
    setopt local_options local_traps err_return

    # TODO an actually useful error message for invalid args

    local -a fifos
    local -a pids
    local server_pid saved_stty

    if [[ -t 0 ]]; then
        saved_stty="$(stty -g)"
    fi

    () {
        trap '
            __command-server-cleanup
            if [[ -n "$server_pid" ]]; then
                if print -nu3 &> /dev/null; then
                    printf '%s' "$server_pid" >&3
                else
                    echo "Server is running at pid $server_pid"
                fi
            fi
        ' EXIT

        local sig sig_return_val
        for sig in INT TERM QUIT HUP; do
            sig_return_val="$((127 + $signals[(Ie)$sig]))"
            trap "
                if [[ -n \"\$server_pid\" ]]; then
                    printf 'Received SIG%s! Killing server %s\\n' $sig \$server_pid
                    kill -$sig \$server_pid || true
                    server_pid=""
                fi
                return $sig_return_val
            " "$sig"
        done

        local stdin stdout stderr status_pipe
        local invocation_id="$RANDOM"
        __command-server-forward-stdio-yes-tty

        python3 "${COMMAND_SERVER_LIB}/../src/command_server.py" \
            "$@" \
            "$stdin" \
            "$stdout" \
            "$stderr" \
            "$status_pipe" &
        server_pid="$!"

        IFS="" read result < "$status_pipe"
        return $result
    } "$@"
}

function command-server-terminate() {
    setopt local_options local_traps err_return

    if [[ $# -ne 1 ]]; then
        printf '%s\n' \
            'Usage: command-server-terminate <socket>' >&2
        return 1
    fi

    __command-server-raw-send \
        "$1" \
        term
}

function command-server-sig() {
    if [[ $# -ne 3 ]]; then
        printf '%s\n' \
            'Usage: command-server-sig <socket> <request-id> <signal>' >&2
        return 1
    fi

    __command-server-raw-send \
        "$1" \
        sig \
        "$2" \
        "$3"
}

function command-server-status() {
    setopt local_options local_traps err_return

    if [[ $# -ne 1 ]]; then
        printf '%s\n' \
            'Usage: command-server-reload <socket>' >&2
        return 1
    fi

    local -a fifos
    local -a pids
    local saved_stty

    if [[ -t 0 ]]; then
        saved_stty="$(stty -g)"
    fi

    () {
        trap __command-server-cleanup EXIT

        local socket="$1"
        local stdin stdout stderr status_pipe

        # TODO signals
        local invocation_id="$RANDOM"
        __command-server-forward-stdio-yes-tty

        printf '%s.%s %s status %s\n' "$$" "$invocation_id" "$socket" "$*" >> "$CommandServerClient[logdir]/client.log"

        __command-server-raw-send \
            "$socket" \
            status \
            "$stdin" \
            "$stdout" \
            "$stderr" \
            "$status_pipe"

        IFS="" read result < "$status_pipe"
        return $result
    } "$@"

}

function __command-server-cleanup() {
    if [[ -n "$saved_stty" ]]; then
        stty "$saved_stty"
    fi

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
}

function __command-server-forward-stdio-yes-tty() {
    status_pipe="${CommandServerClient[rundir]}/$$.$invocation_id.status.pipe"
    fifos+=("$status_pipe")
    mkfifo -m 600 "$status_pipe"

    local stdin_stat stdout_stat stderr_stat
    __command-server-fd-stat 0; stdin_stat="$REPLY"
    __command-server-fd-stat 1; stdout_stat="$REPLY"
    __command-server-fd-stat 2; stderr_stat="$REPLY"

    # Rules:
    #   - forward TTYs together
    #   - when stdout == stderr, forward those togehter
    #   - otherwise, forward separately
    local -A Reply
    if [[ "$stdin_stat" == "$stdout_stat" && "$stdin_stat" == "$stderr_stat" ]]; then
        # All stdio is on the same file
        __command-server-forward-fds 0 1 2
    elif [[ "$stdin_stat" == "$stdout_stat" ]]; then
        # in and out are the same, err is redirected
        __command-server-forward-fds 0 1
        __command-server-forward-fds 2
    elif [[ "$stdin_stat" == "$stderr_stat" ]]; then
        # in and err are the same, out is redirected
        __command-server-forward-fds 0 2
        __command-server-forward-fds 1
    elif [[ "$stdout_stat" == "$stderr_stat" ]]; then
        # out and err are the same, in is redirected
        __command-server-forward-fds 1 2
        __command-server-forward-fds 0
    else
        # all different
        __command-server-forward-fds 0
        __command-server-forward-fds 1
        __command-server-forward-fds 2
    fi

    stdin="$Reply[0]"
    stdout="$Reply[1]"
    stderr="$Reply[2]"
}

function __command-server-forward-fds() {
    local fd

    if [[ -t "$1" ]]; then
        local link="${CommandServerClient[rundir]}/$$.$invocation_id.$1.tty"
        fifos+=("$link")
        for fd; do
            Reply[$fd]="$link"
        done

        local -a socat_args
        if [[ "$1" -eq 0 ]]; then
            local tty="$(tty)"
            if [[ $# -eq 1 ]]; then
                # Just foward stdin -> link
                socat -u "GOPEN:$tty,rawer" "PTY,sane,link=$link" < /dev/null &> /dev/null &
            else
                # Forward $(tty) <-> link
                socat "GOPEN:$tty,rawer" "PTY,sane,link=$link" < /dev/null &> /dev/null &
            fi
        else
            # Forward real fd <- 3 <- link
            socat -U "FD:3" "PTY,rawer,link=$link" 3>&$1 < /dev/null &> /dev/null &
        fi
        pids+=($!)

        # TODO better way of ensuring link exists
        while [[ ! -e "$link" ]]; do
            sleep 0.01
        done

        if [[ -t 0 ]]; then
            stty brkint -ignbrk isig
        fi
    else
        local fifo
        for fd; do
            fifo="${CommandServerClient[rundir]}/$$.$invocation_id.$fd.pipe"
            fifos+=("$fifo")
            mkfifo -m 600 "$fifo"
            Reply[$fd]="$fifo"

            if [[ "$fd" -eq 0 ]]; then
                socat -u "FD:$fd" "GOPEN:$fifo" &> /dev/null &
            else
                socat -U "FD:3" "GOPEN:$fifo" 3>&$fd &> /dev/null &
            fi
            pids+=($!)
        done
    fi
}
