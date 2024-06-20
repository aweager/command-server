#!/bin/zsh

to_forward_1="$1"
to_forward_2="$2"
to_forward_3="$3"
shift 3
nix_develop_args=("$@")

loop_command_args=(
    "${COMMAND_SERVER_LIB}"
    "${to_forward_1}"
    "${to_forward_2}"
    "${to_forward_3}"
)
loop_command=(
    .
    "${0:h}/nix-executor-loop.sh"
)

# Using socat to create an interactive nix develop shell so that shell functions
# and aliases are available. This is particularly useful for the stdenv
# functions buildPhase, installPhase, etc
{
    printf '%s ' "${(@q+)nix_develop_args}"; echo
    printf '%s ' set -- "${(@q+)loop_command_args}" ";" "${(@q+)loop_command}"; echo } | \
    socat \
        -lf /dev/null \
        'STDIN,ignoreeof!!STDOUT,rawer' \
        "EXEC:${0:h}/invoke-nix-develop.zsh,pty,sane,echo=0,ctty,setsid"
