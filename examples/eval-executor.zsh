#!/bin/zsh

function execute-command() {
    "$@"
}

source "./executor-loop.zsh" "$@"
