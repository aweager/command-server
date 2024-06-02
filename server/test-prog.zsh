#!/bin/zsh

echo Hi on stdout
echo Hi on stderr >&2

source "logger.zsh"

log.trace Logging
INDENT="    " log.debug in
INDENT="        " log.info colors
INDENT="        " log.warn with
INDENT="    " log.error indents
log.fatal "yay!"

echo "Please enter some text, then ^D"
cat
echo "Enter some more"
cat

echo Bye!
