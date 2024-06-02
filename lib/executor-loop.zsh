#!/bin/zsh

source "logger.zsh"
zmodload zsh/param/private

private in_fd out_fd
exec {in_fd}<"$1"
exec {out_fd}>"$2"

log.info Executor initialized

while true; do
    () {
        setopt local_options local_traps

        private STDIO_ARGS
        read STDIO_ARGS
        private -a stdio_args=(${(z)STDIO_ARGS})
        private stdin="$stdio_args[1]"
        private stdout="$stdio_args[2]"
        private stderr="$stdio_args[3]"
        private send="$stdio_args[4]"
        private client_pid="$stdio_args[5]"

        trap "
            log.trace Completing with error
            echo -n 1 > '$send'
            echo 'done'
        " EXIT

        log.debug "Client $client_pid requested stdio:" \
                "\n    in  < $stdin" \
                "\n    out > $stdout" \
                "\n    err > $stderr" \
                "\nResult on $send"

        private CMD
        read CMD
        private cmd=(${(z)CMD})

        () {
            emulate -L zsh
            log.trace "Executing $*"
            execute-command "$@"
        } < "$stdin" > "$stdout" 2> "$stderr" "$cmd[@]"
        private result=$?

        log.trace "Writing result $result for client $client_pid"
        echo -n $result > "$send"
        unset send
    }
done <&$in_fd >&$out_fd
