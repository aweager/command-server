#!/bin/zsh

exec 2>&1

IFS="" read -r
nix_develop_args=(${(Q)${(z)REPLY}})

printf '%s '  "Executing: nix develop" "$nix_develop_args[@]"
echo

exec nix develop "$@"
