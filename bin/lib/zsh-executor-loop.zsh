#!/usr/bin/env zsh

# Expectes execute-zsh-command to be defined in the environment

function execute-command() {
    execute-zsh-command "${(@XQ)${(z)1}}"
}

0="${ZERO:-${${0:#$ZSH_ARGZERO}:-${(%):-%N}}}"
0="${${(M)0:#/*}:-$PWD/$0}"

source "${0:a:h}/posix-executor-loop.sh"
