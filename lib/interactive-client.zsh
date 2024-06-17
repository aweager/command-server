#!/bin/zsh

typeset -gH COMMAND_SERVER_LIB="${0:a:h}"

zmodload zsh/zutil
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
    if [[ -t 0 || -t 1 || -t 2 ]]; then
        saved_stty="$(stty -g)"
    fi

    {
        local socket="$1"
        shift

        local stdin stdout stderr status_pipe
        local sig sig_return_val
        for sig in INT TERM QUIT HUP; do
            sig_return_val="$((127 + $signals[(Ie)$sig]))"
            trap "
                echo 'Recevied $sig' >> client.log
                if [[ -n \"\$result\" ]]; then
                    return \$result
                elif [[ -n \"\$request_id\" ]]; then
                    command-server-sig '$socket' \"\$request_id\" '$sig'
                    IFS= read result < \"\$status_pipe\"
                    return \$result
                else
                    echo 'returning $sig_return_val' >> client.log
                    return $sig_return_val
                fi
            " "$sig"
        done

        echo "Client pid: $$" >> client.log
        echo kill -INT $$ >> client.log
        kill -INT $$ 2>> client.log
        echo tried to kill >> client.log

        __command-server-forward-stdio-yes-tty

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

        echo "Waiting for $request_id" >> client.log

        IFS="" read result < "$status_pipe"
        return $result
    } always {
        __command-server-cleanup
    }
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

    if [[ -t 0 || -t 1 || -t 2 ]]; then
        saved_stty="$(stty -g)"
    fi

    {
        local socket="$1"
        local stdin stdout stderr status_pipe

        # TODO signals
        __command-server-forward-stdio-yes-tty

        __command-server-raw-send \
            "$socket" \
            reload \
            "$stdin" \
            "$stdout" \
            "$stderr" \
            "$status_pipe"

        IFS="" read result < "$status_pipe"
        return $result
    } always {
        __command-server-cleanup
    }
}

function command-server-start() {
    setopt local_options local_traps err_return

    local -a fifos
    local -a pids
    local server_pid saved_stty

    if [[ -t 0 || -t 1 || -t 2 ]]; then
        saved_stty="$(stty -g)"
    fi

    {
        local sig sig_return_val
        for sig in INT TERM QUIT HUP; do
            sig_return_val="$((127 + $signals[(Ie)$sig]))"
            trap "
                echo 'Recevied $sig' >> client.log
                if [[ -n \"\$server_pid\" ]]; then
                    kill -$sig \$server_pid
                fi
                return $sig_return_val
            " "$sig"
        done

        local -a arg_log_file arg_log_level arg_socket_address arg_config_file
        zparseopts -D -- \
            -log-file:=arg_log_file \
            -log-level:=arg_log_level \
            -socket-address:=arg_socket_address \
            -config-file:=arg_config_file

        local log_file="/dev/null"
        if [[ -n $arg_log_file ]]; then
            log_file="$arg_log_file[-1]"
        fi

        local -a command_server_args=()

        if [[ -n $arg_log_level ]]; then
            command_server_args+=(
                --log-level "$arg_log_level[-1]"
            )
        fi

        if [[ -n $arg_socket_address ]]; then
            command_server_args+=(
                --socket-address "$arg_socket_address[-1]"
            )
        fi

        if [[ -n $arg_config_file ]]; then
            command_server_args+=(
                --config-file "$arg_config_file[-1]"
            )
        fi

        local stdin stdout stderr status_pipe
        __command-server-forward-stdio-yes-tty

        python3 "${COMMAND_SERVER_LIB}/../src/command_server.py" \
            "$command_server_args[@]" \
            "$stdin" \
            "$stdout" \
            "$stderr" \
            "$status_pipe" &> "$log_file" < /dev/null &
        server_pid="$!"

        IFS="" read result < "$status_pipe"
        return $result
    } always {
        if [[ -n "$server_pid" ]]; then
            echo "Server is running at pid $server_pid"
        fi
        __command-server-cleanup
    }
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
    status_pipe="$(mktemp -u)"
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
        local link="$(mktemp -u)"
        fifos+=("$link")
        for fd; do
            Reply[$fd]="$link"
        done

        local -a socat_args
        if [[ "$#" -eq 1 && "$1" -eq 0 ]]; then
            socat_args+=("-u")
        elif [[ "$1" -ne 0 ]]; then
            socat_args+=("-U")
        fi

        socat_args+=(
            "GOPEN:$TTY,rawer,ignoreeof"
            "PTY,sane,link=$link"
        )

        socat "$socat_args[@]" &> /dev/null &
        pids+=($!)

        # TODO better way of ensuring link exists
        while [[ ! -e "$link" ]]; do
            sleep 0.01
        done

        stty brkint -ignbrk isig < "$TTY"
    else
        local fifo
        for fd; do
            fifo="$(mktemp -u)"
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
