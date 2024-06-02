#!/bin/zsh

function execute-command() {
    printf '%s\n' "Received $*"
}

source "./executor-loop.zsh" "$@"
