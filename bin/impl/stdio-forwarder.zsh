# Functions for forwarding stdio over named pipes or ttys

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

function cleanup-forward() {
    setopt local_options local_traps err_return

    local pid
    for pid in "$pids[@]"; do
        kill -TERM "$pid" &> /dev/null || true
    done
    wait "$pids[@]" || true

    local fifo
    for fifo in "$fifos[@]"; do
        if [[ -e $fifo ]]; then
            rm "$fifo" || true
        fi
    done

    if [[ -n "$saved_stty" ]]; then
        stty "$saved_stty" &> /dev/null || true
    fi
}

function forward-stdio() {
    setopt local_options local_traps err_return

    local stdin_stat stdout_stat stderr_stat
    fd-stat 0; stdin_stat="$REPLY"
    fd-stat 1; stdout_stat="$REPLY"
    fd-stat 2; stderr_stat="$REPLY"

    # Rules:
    #   - forward TTYs together
    #   - when stdout == stderr, forward those togehter
    #   - otherwise, forward separately
    local -A Reply
    if [[ "$stdin_stat" == "$stdout_stat" && "$stdin_stat" == "$stderr_stat" ]]; then
        # All stdio is on the same file
        forward-fds 0 1 2
    elif [[ "$stdin_stat" == "$stdout_stat" ]]; then
        # in and out are the same, err is redirected
        forward-fds 0 1
        forward-fds 2
    elif [[ "$stdin_stat" == "$stderr_stat" ]]; then
        # in and err are the same, out is redirected
        forward-fds 0 2
        forward-fds 1
    elif [[ "$stdout_stat" == "$stderr_stat" ]]; then
        # out and err are the same, in is redirected
        forward-fds 1 2
        forward-fds 0
    else
        # all different
        forward-fds 0
        forward-fds 1
        forward-fds 2
    fi

    stdin="$Reply[0]"
    stdout="$Reply[1]"
    stderr="$Reply[2]"
}

function forward-fds() {
    setopt local_options local_traps err_return

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

function fd-stat() {
    setopt local_options local_traps err_return

    local -A StatOutput
    zstat -H StatOutput -f "$1"
    REPLY="${StatOutput[inode]}:${StatOutput[rdev]}"
}
