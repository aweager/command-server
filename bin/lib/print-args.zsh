#!/usr/bin/env zsh

function execute-zsh-command() {
    echo "In working dir: $PWD" >&2
    echo "Executing command:"
    printf '    %s\n' "$@"

    "$@"
}

source "zsh-executor-loop.zsh"
