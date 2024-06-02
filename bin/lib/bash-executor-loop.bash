#!/usr/bin/env bash

# Expectes execute-bash-command to be defined in the environment

# From https://stackoverflow.com/questions/26067249/reading-quoted-escaped-arguments-correctly-from-a-string
shlex_split() {
    python3 -c '
import shlex, sys
for item in shlex.split(sys.stdin.read()):
    sys.stdout.write(item + "\0")
'
}

execute-command () {
    command_array=()

    while IFS="" read -r -r ''; do
        command_array+=( "$REPLY" )
    done < <(shlex_split <<<"$1")

    execute-bash-command "${command_array[@]}"
}

source "$(dirname "$BASH_SOURCE")/posix-executor-loop.sh"
