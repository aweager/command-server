#!/bin/sh

to_forward_1="$1"
to_forward_2="$2"
to_forward_3="$3"
shift 3

printf '%s '  "Executing: nix develop" "$@"
echo

# TODO: how to get access to shell functions and aliases
exec nix develop "$@" -c \
    "$(dirname "$0")/nix-executor-loop.sh" \
    "${COMMAND_SERVER_LIB}" \
    "${to_forward_1}" \
    "${to_forward_2}" \
    "${to_forward_3}"
